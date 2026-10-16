from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
import torch
import onnxruntime
from insightface.app.common import Face
from insightface.model_zoo import get_model
from insightface.utils import face_align
from lib.schemas import EmbeddingRecord, FaceDetection, PredictResult, AlignedFace
from lib.services.ai_detector import AIImageDetector
from lib.storage.base import EmbeddingStoreProtocol
from lib.storage.blob_store import BlobStore
import logging

logger = logging.getLogger(__name__)


class FaceService:
    # Fotos requeridas para registrar una identidad y su nombre en los mensajes de validación
    REGISTRATION_POSES: dict[str, str] = {
        "front_close": "frontal de cerca",
        "front_far": "frontal de lejos",
        "profile_left": "perfil izquierdo",
        "profile_right": "perfil derecho",
    }

    def __init__(
        self,
        store: EmbeddingStoreProtocol,
        similarity_metric: str,
        similarity_threshold: float,
        face_size: int,
        model_path: Path,
        blob_store: BlobStore | None = None,
        detector_path: Path | None = None,
        det_score_threshold: float = 0.5,
        det_input_size: int = 640,
        min_face_size: int = 20,
        align_margin: float = 0.5,
        pose_model_path: Path | None = None,
        frontal_max_yaw: float = 20.0,
        profile_min_yaw: float = 45.0,
        close_far_min_ratio: float = 1.3,
        registration_min_similarity: float = 0.3,
        ai_detector: AIImageDetector | None = None,
    ) -> None:
        self.store = store
        self.similarity_metric = similarity_metric
        self.similarity_threshold = similarity_threshold
        self.face_size = face_size
        self.model: any = self._load_model(model_path)
        if blob_store is None:
            raise ValueError("A blob store is required")
        self.blob_store = blob_store
        self.det_score_threshold = det_score_threshold
        self.det_input_size = det_input_size
        self.min_face_size = min_face_size
        self.align_margin = align_margin
        self.detector: any = self._load_detector(detector_path)
        self.frontal_max_yaw = frontal_max_yaw
        self.profile_min_yaw = profile_min_yaw
        self.close_far_min_ratio = close_far_min_ratio
        self.registration_min_similarity = registration_min_similarity
        self.pose_model: any = self._load_pose_model(pose_model_path)
        if ai_detector is None:
            raise ValueError("An AI image detector is required")
        self.ai_detector = ai_detector


    @staticmethod
    def _clip_xyxy(
        x1: int, y1: int, x2: int, y2: int, height: int, width: int
    ) -> tuple[int, int, int, int]:
        x1 = max(0, min(x1, width - 1))
        x2 = max(0, min(x2, width))
        y1 = max(0, min(y1, height - 1))
        y2 = max(0, min(y2, height))
        if x2 <= x1:
            x2 = min(x1 + 1, width)
        if y2 <= y1:
            y2 = min(y1 + 1, height)
        return x1, y1, x2, y2

    @staticmethod
    def _kps_to_keypoints_dict(kps: np.ndarray | None) -> dict[str, list[int]]:
        if kps is None or len(kps) == 0:
            return {}
        return {
            f"k{i}": [int(round(float(kps[i, 0]))), int(round(float(kps[i, 1])))]
            for i in range(len(kps))
        }


    def _load_model(self, model_path: Path) -> any:
        mp = Path(model_path)
        if not mp.exists():
            raise ValueError(f"Model path does not exist: {model_path}")
        suf = mp.suffix.lower()
        if suf == ".pth":
            return torch.load(mp, map_location="cpu", weights_only=False)
        if suf == ".onnx":
            return onnxruntime.InferenceSession(str(mp))
        raise ValueError(f"Unsupported model format (expected .pth or .onnx): {model_path}")

    def _load_detector(self, detector_path: Path | None) -> any:
        """
        Load the face detector once (called from __init__).
        SCRFD (InsightFace): returns boxes with score and 5 landmarks per face.
        """
        if detector_path is None or not Path(detector_path).exists():
            raise ValueError(f"Detector path does not exist: {detector_path}")
        detector = get_model(str(detector_path), providers=["CPUExecutionProvider"])
        detector.prepare(
            ctx_id=-1,
            input_size=(self.det_input_size, self.det_input_size),
            det_thresh=self.det_score_threshold,
        )
        return detector

    def _load_pose_model(self, pose_model_path: Path | None) -> any:
        """
        Landmarks 3D de InsightFace (1k3d68): estima la pose de la cabeza (pitch, yaw, roll)
        para validar las fotos frontales y de perfil del registro.
        """
        if pose_model_path is None or not Path(pose_model_path).exists():
            raise ValueError(f"Pose model path does not exist: {pose_model_path}")
        pose_model = get_model(str(pose_model_path), providers=["CPUExecutionProvider"])
        pose_model.prepare(ctx_id=-1)
        return pose_model

    @staticmethod
    def _encode_jpeg(image: np.ndarray) -> bytes:
        ok, buf = cv2.imencode(".jpg", image)
        if not ok:
            raise ValueError("Could not encode image")
        return buf.tobytes()

    def _load_image(self, data: bytes) -> np.ndarray:
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Could not read image")
        # BGR uint8 (InsightFace / OpenCV convention)
        return image
    
    @staticmethod
    def _iou(a: np.ndarray, b: np.ndarray) -> float:
        """Intersection over union between two boxes (x1, y1, x2, y2)."""
        ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
        ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
        return float(inter / union) if union > 0 else 0.0
    
    def detect_faces(self, image: np.ndarray) -> list[tuple[int, int, int, int]]:
        """
        Each box is (x1, y1, x2, y2) in pixels (InsightFace convention).
        Return a list of tuples with the coordinates of the faces detected in the image.
        """
        height, width = image.shape[:2]
        bboxes, _ = self.detector.detect(image, max_num=0)
        boxes: list[tuple[int, int, int, int]] = []
        for x1, y1, x2, y2, _score in bboxes:
            if min(x2 - x1, y2 - y1) < self.min_face_size:
                continue
            boxes.append(
                self._clip_xyxy(
                    int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)),
                    height, width,
                )
            )
        return boxes

    def align_face(
        self, image: np.ndarray, box: tuple[int, int, int, int]
    ) -> AlignedFace:
        """
        Crop using box (x1, y1, x2, y2) and run FaceAnalysis on the crop.
        Return an AlignedFace object.
        """
        height, width = image.shape[:2]
        x1, y1, x2, y2 = box

        # Recorte con margen alrededor de la caja para que el detector encuentre los landmarks
        mx = int((x2 - x1) * self.align_margin)
        my = int((y2 - y1) * self.align_margin)
        cx1, cy1, cx2, cy2 = self._clip_xyxy(x1 - mx, y1 - my, x2 + mx, y2 + my, height, width)
        crop = image[cy1:cy2, cx1:cx2]

        bboxes, kpss = self.detector.detect(crop, max_num=0)
        if len(bboxes) == 0 or kpss is None:
            # Sin landmarks no se puede alinear: se usa el recorte de la caja redimensionado
            logger.warning(f"No landmarks found for box {box}; using unaligned crop")
            face_img = cv2.resize(image[y1:y2, x1:x2], (self.face_size, self.face_size))
            return AlignedFace(bbox=box, keypoints=None, image=face_img)

        # Quedarse con la detección del recorte que mejor coincide con la caja original
        target = np.array([x1 - cx1, y1 - cy1, x2 - cx1, y2 - cy1], dtype=np.float32)
        best = max(range(len(bboxes)), key=lambda i: self._iou(bboxes[i, :4], target))
        kps = kpss[best] + np.array([cx1, cy1], dtype=np.float32)

        # Transformación de similitud hacia la plantilla ArcFace (misma que en entrenamiento)
        face_img = face_align.norm_crop(image, landmark=kps, image_size=self.face_size)
        return AlignedFace(
            bbox=box,
            keypoints=kps - np.array([x1, y1], dtype=np.float32),
            image=face_img,
        )

    def extract_embedding_from_face(self, face: AlignedFace) -> list[float]:
        """
        Extract embedding from face.
        Return a list of floats representing the embedding of the face.
        """
        if face.embedding is not None:
            return face.embedding

        # Preprocesamiento ArcFace: BGR->RGB, (x - 127.5) / 127.5, HWC->NCHW
        blob = cv2.dnn.blobFromImage(
            face.image,
            scalefactor=1.0 / 127.5,
            size=(self.face_size, self.face_size),
            mean=(127.5, 127.5, 127.5),
            swapRB=True,
        )
        input_name = self.model.get_inputs()[0].name
        emb = self.model.run(None, {input_name: blob})[0][0]
        emb = emb / (np.linalg.norm(emb) + 1e-12)
        return emb.astype(float).tolist()

    def _cosine(self, a: np.ndarray, b: np.ndarray) -> float:
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)

    def _l2_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        dist = float(np.linalg.norm(a - b))
        return 1.0 / (1.0 + dist)

    def similarity(self, query: list[float], ref: list[float]) -> float:
        a = np.asarray(query, dtype=np.float32)
        b = np.asarray(ref, dtype=np.float32)
        if self.similarity_metric.lower() == "l2":
            return self._l2_similarity(a, b)
        return self._cosine(a, b)

    def identify(self, query_embedding: list[float]) -> tuple[str, float]:
        records = self.store.all()
        if not records:
            return "unknown", 0.0

        best_label = "unknown"
        best_score = -1.0
        for record in records:
            score = self.similarity(query_embedding, record.embedding)
            if score > best_score:
                best_score = score
                best_label = record.etiqueta

        if best_score < self.similarity_threshold:
            return "unknown", max(best_score, 0.0)
        return best_label, best_score

    def is_registered(self, identity: str) -> bool:
        """True si la identidad completó un registro de 4 fotos."""
        return any(
            record.etiqueta == identity and "registration_id" in record.metadata
            for record in self.store.all()
        )

    def estimate_yaw(self, image: np.ndarray, box: tuple[int, int, int, int]) -> float:
        """
        Giro horizontal de la cabeza en grados: ~0 frontal, ~±90 perfil.
        El signo indica hacia qué lado mira (se invierte si la cámara espeja la imagen).
        """
        face = Face(bbox=np.asarray(box, dtype=np.float32))
        self.pose_model.get(image, face)
        _pitch, yaw, _roll = face.pose
        return float(yaw)

    def _validate_registration(self, images: dict[str, bytes]) -> dict[str, dict]:
        """
        Valida las 4 fotos del registro y devuelve, por pose, la imagen, la caja, el yaw
        y el alto del rostro relativo al alto de la imagen. Junta todos los problemas
        en un único ValueError para que el usuario pueda corregirlos de una vez.
        """
        errors: list[str] = []
        shots: dict[str, dict] = {}
        for pose, label in self.REGISTRATION_POSES.items():
            # Una foto generada o alterada con IA no se analiza
            ai_detection = self.ai_detector.check(images[pose])
            if ai_detection.is_ai_generated:
                errors.append(f"{label}: la imagen parece generada o alterada con IA ({ai_detection.evidence})")
                continue
            image = self._load_image(images[pose])
            boxes = self.detect_faces(image)
            if len(boxes) != 1:
                errors.append(f"{label}: se detectaron {len(boxes)} rostros, debe haber exactamente uno")
                continue
            box = boxes[0]
            shots[pose] = {
                "image": image,
                "box": box,
                "yaw": self.estimate_yaw(image, box),
                "height_ratio": (box[3] - box[1]) / image.shape[0],
            }
            logger.info(f"Registration {pose}: box={box} yaw={shots[pose]['yaw']:.1f}")

        for pose in ("front_close", "front_far"):
            if pose in shots and abs(shots[pose]["yaw"]) > self.frontal_max_yaw:
                errors.append(
                    f"{self.REGISTRATION_POSES[pose]}: el rostro no está de frente "
                    f"(giro {abs(shots[pose]['yaw']):.0f}°, máximo {self.frontal_max_yaw:.0f}°)"
                )
        for pose in ("profile_left", "profile_right"):
            if pose in shots and abs(shots[pose]["yaw"]) < self.profile_min_yaw:
                errors.append(
                    f"{self.REGISTRATION_POSES[pose]}: no es un perfil "
                    f"(giro {abs(shots[pose]['yaw']):.0f}°, mínimo {self.profile_min_yaw:.0f}°)"
                )

        left, right = shots.get("profile_left"), shots.get("profile_right")
        if (
            left and right
            and min(abs(left["yaw"]), abs(right["yaw"])) >= self.profile_min_yaw
            and np.sign(left["yaw"]) == np.sign(right["yaw"])
        ):
            errors.append("las dos fotos de perfil muestran el mismo lado de la cara (se necesita una de cada lado)")

        close, far = shots.get("front_close"), shots.get("front_far")
        if close and far and close["height_ratio"] < far["height_ratio"] * self.close_far_min_ratio:
            errors.append(
                f"la foto frontal de cerca debe mostrar el rostro al menos {self.close_far_min_ratio:g}x "
                f"más grande que la de lejos (cerca: {close['height_ratio']:.0%} del alto de la imagen, "
                f"lejos: {far['height_ratio']:.0%})"
            )

        if errors:
            raise ValueError("Registro rechazado: " + "; ".join(errors))
        return shots

    def register_identity(
        self, identity: str, images: dict[str, bytes], metadata: dict[str, object]
    ) -> tuple[str, str]:
        """
        Registra una identidad a partir de 4 fotos (frontal de cerca, frontal de lejos y
        ambos perfiles). Guarda un embedding por pose y los rostros alineados en el almacenamiento
        de objetos. Devuelve (registration_id, objeto con los 4 rostros alineados).
        """
        shots = self._validate_registration(images)

        aligned = {pose: self.align_face(shot["image"], shot["box"]) for pose, shot in shots.items()}
        embeddings = {pose: self.extract_embedding_from_face(face) for pose, face in aligned.items()}

        # Las 4 fotos tienen que ser de la misma persona (se compara contra la frontal de cerca)
        reference = np.asarray(embeddings["front_close"], dtype=np.float32)
        mismatched: list[str] = []
        for pose, emb in embeddings.items():
            score = self._cosine(reference, np.asarray(emb, dtype=np.float32))
            if pose != "front_close" and score < self.registration_min_similarity:
                mismatched.append(f"{self.REGISTRATION_POSES[pose]} (similitud {score:.2f})")
        if mismatched:
            raise ValueError(
                "Registro rechazado: estas fotos no parecen ser de la misma persona que la frontal "
                f"de cerca (mínimo {self.registration_min_similarity:g}): " + ", ".join(mismatched)
            )

        # Un rostro solo puede pertenecer a una identidad: se rechaza si alguna foto se reconoce
        # como otra persona ya registrada (mismo criterio y umbral que identify). El mensaje no
        # nombra a la otra persona para no exponer datos de otra cuenta.
        for pose, emb in embeddings.items():
            label, score = self.identify(emb)
            if label not in ("unknown", identity):
                logger.warning(f"Registration of {identity} rejected: {pose} matches {label} ({score:.2f})")
                raise ValueError("Registro rechazado: este rostro ya está registrado en otra cuenta")

        registration_id = str(uuid4())
        records: list[EmbeddingRecord] = []
        for pose, face in aligned.items():
            face_object = f"registrations/{identity}/{registration_id}/{pose}.jpg"
            self.blob_store.upload(face_object, self._encode_jpeg(face.image), "image/jpeg")
            records.append(
                EmbeddingRecord(
                    id_imagen=str(uuid4()),
                    embedding=embeddings[pose],
                    path=face_object,
                    etiqueta=identity,
                    metadata={
                        **metadata,
                        "pose": pose,
                        "yaw": round(shots[pose]["yaw"], 1),
                        "registration_id": registration_id,
                    },
                )
            )
        for record in records:
            self.store.append(record)

        summary_object = f"registrations/{identity}/{registration_id}/summary.jpg"
        summary = np.hstack([aligned[pose].image for pose in self.REGISTRATION_POSES])
        self.blob_store.upload(summary_object, self._encode_jpeg(summary), "image/jpeg")
        logger.info(f"Identity registered: {identity} with {len(records)} poses ({registration_id})")
        return registration_id, summary_object

    def predict(self, image: bytes, source_object: str) -> PredictResult:
        # Si la imagen fue generada o alterada con IA no se corre la detección de rostros
        ai_detection = self.ai_detector.check(image)
        if ai_detection.is_ai_generated:
            logger.info(f"AI-generated image, skipping face detection: {source_object} ({ai_detection.evidence})")
            detections: list[FaceDetection] = []
        else:
            detections = self._recognize_faces(image)

        detected_people = sorted({item.name for item in detections if item.label != "unknown"})
        return PredictResult(
            source_path=source_object,
            ai_detection=ai_detection,
            detections=detections,
            detected_people=detected_people,
        )

    def _recognize_faces(self, data: bytes) -> list[FaceDetection]:
        image = self._load_image(data)
        faces = self.detect_faces(image)
        display_names = {
            record.etiqueta: record.metadata.get("display_name") or record.etiqueta
            for record in self.store.all()
        }
        detections: list[FaceDetection] = []
        for (x1, y1, x2, y2) in faces:
            aligned = self.align_face(image, (x1, y1, x2, y2))
            embedding = self.extract_embedding_from_face(aligned)
            label, score = self.identify(embedding)
            kps = getattr(aligned, "keypoints", None)
            kps_arr = np.asarray(kps) if kps is not None else None
            detections.append(
                FaceDetection(
                    bbox=[x1, y1, x2, y2],
                    keypoints=self._kps_to_keypoints_dict(kps_arr),
                    label=label,
                    name=display_names.get(label, label),
                    score=round(float(score), 4),
                )
            )
        return detections
