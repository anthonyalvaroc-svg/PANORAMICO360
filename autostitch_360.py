import sys
import os
import cv2
import numpy as np
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout,
    QPushButton, QLabel, QFileDialog, QSpinBox, QComboBox,
    QFormLayout, QMessageBox, QProgressBar
)
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import Qt, QThread, pyqtSignal


class StitcherThread(QThread):
    finished = pyqtSignal(object, str)

    def __init__(self, image_paths, mode, scale, width, height):
        super().__init__()
        self.image_paths = image_paths
        self.mode = mode
        self.scale = scale / 100.0
        self.target_w = width
        self.target_h = height

    def run(self):
        images = []
        for path in self.image_paths:
            img_array = np.fromfile(path, np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if img is not None:
                if self.scale != 1.0:
                    img = cv2.resize(
                        img, (0, 0), fx=self.scale, fy=self.scale
                    )
                images.append(img)

        if len(images) < 2:
            self.finished.emit(None, "Se necesitan al menos 2 imágenes.")
            return

        stitch_mode = (
            cv2.Stitcher_PANORAMA
            if self.mode == "Panorama"
            else cv2.Stitcher_SCANS
        )
        stitcher = cv2.Stitcher_create(stitch_mode)
        status, pano = stitcher.stitch(images)

        if status == cv2.Stitcher_OK:
            if self.target_w > 0 and self.target_h > 0:
                pano = cv2.resize(pano, (self.target_w, self.target_h))
            self.finished.emit(pano, "Unión completada con éxito.")
        else:
            self.finished.emit(None, f"Error en unión (Código {status})")
class Viewer360Widget(QWidget):
    def __init__(self):
        super().__init__()
        self.panorama = None
        self.yaw = 0.0
        self.pitch = 0.0
        self.fov = 90.0
        self.last_mouse_pos = None

        layout = QVBoxLayout(self)
        txt = "Arrastra con clic izquierdo para girar 360° | Rueda: Zoom"
        info = QLabel(txt)
        info.setAlignment(Qt.AlignCenter)
        layout.addWidget(info)

        self.canvas = QLabel("Genera una panorámica para ver el 360°")
        self.canvas.setAlignment(Qt.AlignCenter)
        self.canvas.setStyleSheet(
            "background-color: #1e1e1e; color: #aaa; border: 1px solid #444;"
        )
        self.canvas.setMinimumSize(640, 400)
        layout.addWidget(self.canvas, 1)

    def set_panorama(self, cv_img):
        self.panorama = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
        self.yaw = 0.0
        self.pitch = 0.0
        self.render_view()

    def render_view(self):
        if self.panorama is None:
            return
        h_pano, w_pano, _ = self.panorama.shape
        out_w, out_h = self.canvas.width(), self.canvas.height()
        if out_w < 10 or out_h < 10:
            return

        fov_rad = np.deg2rad(self.fov)
        f = 0.5 * out_w / np.tan(0.5 * fov_rad)
        u, v = np.meshgrid(np.arange(out_w), np.arange(out_h))
        x = u - out_w / 2.0
        y = v - out_h / 2.0
        z = np.full_like(x, f)

        p_rad = np.deg2rad(self.pitch)
        y_rad = np.deg2rad(self.yaw)

        Rx = np.array([,
            [0, np.cos(p_rad), -np.sin(p_rad)],
            [0, np.sin(p_rad), np.cos(p_rad)]
        ])
        Ry = np.array([
            [np.cos(y_rad), 0, np.sin(y_rad)],
,
            [-np.sin(y_rad), 0, np.cos(y_rad)]
        ])
        R = Ry @ Rx

        dirs = np.stack([x, y, z], axis=-1) @ R.T
        dirs /= np.linalg.norm(dirs, axis=-1, keepdims=True)

        lon = np.arctan2(dirs[..., 0], dirs[..., 2])
        lat = np.arcsin(np.clip(dirs[..., 1], -1.0, 1.0))

        map_x = ((lon / (2 * np.pi) + 0.5) * w_pano).astype(np.float32)
        map_y = ((lat / np.pi + 0.5) * h_pano).astype(np.float32)

        view = cv2.remap(
            self.panorama, map_x, map_y,
            cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP
        )
        qimg = QImage(
            view.data, out_w, out_h, 3 * out_w, QImage.Format_RGB888
        )
        self.canvas.setPixmap(QPixmap.fromImage(qimg))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.last_mouse_pos = event.pos()

    def mouseMoveEvent(self, event):
        if self.last_mouse_pos is not None and self.panorama is not None:
            dx = event.x() - self.last_mouse_pos.x()
            dy = event.y() - self.last_mouse_pos.y()
            self.yaw -= dx * 0.25
            self.pitch = np.clip(self.pitch + dy * 0.25, -85.0, 85.0)
            self.last_mouse_pos = event.pos()
            self.render_view()

    def mouseReleaseEvent(self, event):
        self.last_mouse_pos = None

    def wheelEvent(self, event):
        if self.panorama is not None:
            delta = event.angleDelta().y() / 120.0
            self.fov = np.clip(self.fov - delta * 5.0, 30.0, 120.0)
            self.render_view()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.render_view()
class AutoStitchClone(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Panorama Stitcher & Visor 360°")
        self.resize(900, 650)
        self.image_paths = []
        self.result_pano = None

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.tab1 = QWidget()
        self.tab2 = QWidget()
        self.tab3 = QWidget()
        self.tab4 = QWidget()
        self.tab5 = QWidget()
        self.tab6 = Viewer360Widget()

        self.tabs.addTab(self.tab1, "1. Imágenes")
        self.tabs.addTab(self.tab2, "2. Salida")
        self.tabs.addTab(self.tab3, "3. Fusión")
        self.tabs.addTab(self.tab4, "4. Cámara")
        self.tabs.addTab(self.tab5, "5. Vista 2D")
        self.tabs.addTab(self.tab6, "6. Diagrama 360°")

        self.setup_tabs()

    def setup_tabs(self):
        # Tab 1
        l1 = QVBoxLayout(self.tab1)
        btn_load = QPushButton("Seleccionar Imágenes (Soporta '°')")
        btn_load.clicked.connect(self.select_images)
        l1.addWidget(btn_load)

        self.lbl_files = QLabel("Ninguna imagen cargada.")
        l1.addWidget(self.lbl_files)

        self.btn_stitch = QPushButton("Iniciar Unión (Stitch)")
        self.btn_stitch.setStyleSheet(
            "font-weight: bold; padding: 10px; "
            "background-color: #2b78e4; color: white;"
        )
        self.btn_stitch.clicked.connect(self.start_stitching)
        l1.addWidget(self.btn_stitch)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        l1.addWidget(self.progress)
        l1.addStretch()

        # Tab 2
        l2 = QFormLayout(self.tab2)
        self.spin_w = QSpinBox()
        self.spin_w.setRange(0, 16384)
        self.spin_w.setValue(2048)
        self.spin_h = QSpinBox()
        self.spin_h.setRange(0, 8192)
        self.spin_h.setValue(1024)
        self.spin_q = QSpinBox()
        self.spin_q.setRange(10, 100)
        self.spin_q.setValue(90)
        l2.addRow("Ancho (0 = auto):", self.spin_w)
        l2.addRow("Alto (0 = auto):", self.spin_h)
        l2.addRow("Calidad JPEG (%):", self.spin_q)

        # Tab 3
        l3 = QFormLayout(self.tab3)
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["Panorama", "Scans (Planos)"])
        self.spin_scale = QSpinBox()
        self.spin_scale.setRange(10, 100)
        self.spin_scale.setValue(100)
        l3.addRow("Proyección:", self.combo_mode)
        l3.addRow("Escala (%):", self.spin_scale)

        # Tab 4
        l4 = QVBoxLayout(self.tab4)
        l4.addWidget(QLabel("Calibración automática de lente activada."))
        l4.addStretch()

        # Tab 5
        l5 = QVBoxLayout(self.tab5)
        self.lbl_prev = QLabel("Aquí aparecerá el resultado 2D.")
        self.lbl_prev.setAlignment(Qt.AlignCenter)
        l5.addWidget(self.lbl_prev, 1)
        btn_save = QPushButton("Guardar Panorámica")
        btn_save.clicked.connect(self.save_panorama)
        l5.addWidget(btn_save)
    def select_images(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Seleccionar fotos", "", "Imágenes (*.jpg *.jpeg *.png)"
        )
        if files:
            self.image_paths = files
            self.lbl_files.setText(f"{len(files)} imágenes cargadas.")

    def start_stitching(self):
        if len(self.image_paths) < 2:
            QMessageBox.warning(self, "Aviso", "Elige mínimo 2 imágenes.")
            return
        self.btn_stitch.setEnabled(False)
        self.progress.show()

        self.thread = StitcherThread(
            self.image_paths,
            self.combo_mode.currentText(),
            self.spin_scale.value(),
            self.spin_w.value(),
            self.spin_h.value()
        )
        self.thread.finished.connect(self.on_finished)
        self.thread.start()

    def on_finished(self, pano, msg):
        self.progress.hide()
        self.btn_stitch.setEnabled(True)
        if pano is not None:
            self.result_pano = pano
            rgb = cv2.cvtColor(pano, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
            self.lbl_prev.setPixmap(
                QPixmap.fromImage(qimg).scaled(
                    800, 450, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )
            self.tab6.set_panorama(pano)
            QMessageBox.information(self, "Éxito", msg)
            self.tabs.setCurrentIndex(5)
        else:
            QMessageBox.critical(self, "Error", msg)

    def save_panorama(self):
        if self.result_pano is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar", "panoramica_360.jpg", "JPEG (*.jpg)"
        )
        if path:
            ext = os.path.splitext(path)[1]
            _, buf = cv2.imencode(
                ext, self.result_pano,
                [int(cv2.IMWRITE_JPEG_QUALITY), self.spin_q.value()]
            )
            buf.tofile(path)
            QMessageBox.information(self, "Listo", "Imagen guardada.")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = AutoStitchClone()
    win.show()
    sys.exit(app.exec_())
