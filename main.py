import sys
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QPushButton
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import QThread, pyqtSignal
from pypylon import pylon
import cv2

class CameraEvent:
    def __init__(self):
        self.camera = None

    def create_camera(self):
        tl_factory = pylon.TlFactory.GetInstance()
        devices = tl_factory.EnumerateDevices()
        self.camera = pylon.InstantCamera(tl_factory.CreateDevice(devices[0])) if devices else None
        print(devices[0].GetFriendlyName()) if devices else print("Camera not found")

    def open_camera(self):
        if self.camera:
            self.camera.Open()
            print("Camera open successfully")
            return self.camera

    def close_camera(self):
        if self.camera:
            self.camera.Close()
            print("The camera is closed")

    def start_grabbing(self):
        if self.camera and not self.camera.IsGrabbing():
            self.camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)

    def stop_grabbing(self):
        if self.camera and self.camera.IsGrabbing():
            self.camera.StopGrabbing()

    def grab_frame(self):
        if self.camera and self.camera.IsGrabbing():
            grab_result = self.camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
            if grab_result.GrabSucceeded():
                frame = cv2.cvtColor(grab_result.Array, cv2.COLOR_BGR2RGB)
                grab_result.Release()
                return frame
            else:
                print("Error grabbing frame:", grab_result.GetErrorDescription())
        else:
            print("Camera not grabbing frames")
        return None

class CameraApp(QWidget):
    def __init__(self):
        super().__init__()

        self.camera_event = CameraEvent()

        self.image_label = QLabel(self)
        self.start_button = QPushButton('Start Camera', self)
        self.stop_button = QPushButton('Stop Camera', self)

        self.layout = QVBoxLayout(self)
        self.layout.addWidget(self.start_button)
        self.layout.addWidget(self.stop_button)
        self.layout.addWidget(self.image_label)

        self.start_button.clicked.connect(self.start_camera)
        self.stop_button.clicked.connect(self.stop_camera)

        self.camera_thread = QThread(self)
        self.camera_thread.run = self.camera_event_loop
        self.camera_thread.start()

        self.setWindowTitle("Camera Viewer")
        self.setFixedSize(800, 600)

    def start_camera(self):
        self.camera_event.create_camera()
        self.camera_event.open_camera()
        print("Starting camera..")

    def stop_camera(self):
        self.camera_event.stop_grabbing()
        self.camera_event.close_camera()

    def camera_event_loop(self):
        self.camera_event.start_grabbing()
        while True:
            frame = self.camera_event.grab_frame()
            if frame is not None:
                self.update_display(frame)

    def update_display(self, frame):
        height, width = frame.shape
        bytes_per_line = 3 * width
        q_image = QImage(frame.data, width, height, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(q_image)
        self.image_label.setPixmap(pixmap)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = CameraApp()
    window.show()
    sys.exit(app.exec_())
