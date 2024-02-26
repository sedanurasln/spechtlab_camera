from datetime import datetime
import sys
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTabWidget, QFileDialog, QSlider, QFrame, QCheckBox, QSpinBox, QComboBox, QMessageBox, QGroupBox
from PyQt5.QtGui import QImage, QPixmap, QFont, QColor, QPalette
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
import cv2
from pypylon import pylon
import time
import collections
import os

button_style = '''
    QPushButton {
        background-color: #354F52;
        color: white;
        border: 1px solid #8B3626;
        border-radius: 5px;
        padding: 5px 10px;
    }
    QPushButton:hover {
        background-color: #2f3e46;
    }
'''

class CameraThread(QThread):
    frame_ready = pyqtSignal(object)
    fps_changed = pyqtSignal(float)
    

    def __init__(self, parent=None):
        super(CameraThread, self).__init__(parent)
        self.is_running = False
        self.latest_frame = None
        self.continuous_shooting = False
        self.video_writer = None
        self.exposure_value = 35000.0
        self.sync_free_run_timer_rate = 30  
        self.last_frame_time = time.time()
        self.fps_history = collections.deque(maxlen=10)
        self.trigger_mode_enabled = False
        self.sync_free_run_timer_enabled = False
        self.camera = None  

    def run(self):
        self.is_running = True
        self.camera = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateFirstDevice())
        self.camera.Open()
        self.camera.ExposureTimeMode.Mode = 'Contiunes'
        self.camera.ExposureTimeAbs.Value = self.exposure_value
        self.camera.UserSetSelector.SetValue('UserSet1')
        self.camera.UserSetSave.Execute()
        self.camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)

        while self.is_running:
            grab_result = self.camera.RetrieveResult(25000, pylon.TimeoutHandling_ThrowException)

            if grab_result.GrabSucceeded():
                image = grab_result.Array
                self.latest_frame = image
                self.frame_ready.emit(image)

                if self.continuous_shooting and self.video_writer is not None:
                    self.video_writer.write(image)

                current_time = time.time()
                fps = 1.0 / (current_time - self.last_frame_time)
                self.last_frame_time = current_time

                self.fps_history.append(fps)

                avg_fps = sum(self.fps_history) / len(self.fps_history)
                self.fps_changed.emit(avg_fps)

            grab_result.Release()

        self.camera.StopGrabbing()
        self.camera.Close()
        if self.video_writer is not None:
            self.video_writer.release()

    def set_trigger_mode(self, enabled):
        self.trigger_mode_enabled = enabled
        if self.camera :
            if enabled:
                self.camera.TriggerMode.SetValue('On')
            else:
                self.camera.TriggerMode.SetValue('Off')

    def set_sync_free_run_timer(self, enabled):
        self.sync_free_run_timer_enabled = enabled

    def stop(self):
        self.is_running = False

    def grab_frame(self):
        return self.latest_frame

    def set_continuous_shooting(self, value):
        self.continuous_shooting = value

    def set_exposure_value(self, value):
        self.exposure_value = value
        if self.camera:
            self.camera.ExposureTimeAbs.Value = value

    def set_sync_free_run_timer_rate(self, rate):
        self.sync_free_run_timer_rate = rate
        if self.camera:
            self.camera.SyncFreeRunTimerTriggerRateAbs.SetValue(rate)

    def sync_free_run_timer_update_execute(self):
        if self.sync_free_run_timer_enabled:
            self.camera.SyncFreeRunTimerUpdate.Execute()

    def set_trigger_source(self, source):
        if self.camera is not None:
            if source == "Line1":
                self.camera.TriggerSelector.SetValue("FrameStart")
                self.camera.TriggerSource.SetValue("Line1")
            elif source == "Line3":
                self.camera.TriggerSelector.SetValue("FrameStart")
                self.camera.TriggerSource.SetValue("Line3")
            elif source == "Action1":
                self.camera.TriggerSelector.SetValue("FrameStart")
                self.camera.TriggerSource.SetValue("Action1")
    

class MainPage(QWidget):
    def __init__(self, camera_thread):
        super().__init__()
        self.camera_thread = camera_thread
        self.init_ui()

        self.flash_timer = QTimer(self)
        self.flash_timer.timeout.connect(self.flash_button)
        self.flash_color = None
        self.is_flashing = False  
        self.buffered_frames = collections.defaultdict(collections.deque)
        

    def init_ui(self):
        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignCenter)  

        self.start_button = self.create_button('Start Camera', self.start_camera_handler)
        self.stop_button = self.create_button('Stop Camera', self.stop_camera)
        self.single_shot_button = self.create_button('Single Shot', self.single_shot)
        self.continuous_button = self.create_button('Continuous Shot', self.continuous_shot_manager)
        self.save_button = self.create_button('Save', self.save)

        self.stop_button.setEnabled(False)
        self.continuous_button.setEnabled(False)
        self.single_shot_button.setEnabled(False)
        self.save_button.setEnabled(False)

        self.start_button.setStyleSheet(button_style)
        self.stop_button.setStyleSheet(button_style)
        self.single_shot_button.setStyleSheet(button_style)
        self.continuous_button.setStyleSheet(button_style)
        self.save_button.setStyleSheet(button_style)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.image_label, alignment=Qt.AlignCenter)  

        button_layout = QHBoxLayout()

        left_buttons_layout = QVBoxLayout()
        left_buttons_layout.addWidget(self.start_button)
        left_buttons_layout.addWidget(self.stop_button)
        button_layout.addLayout(left_buttons_layout)

        center_buttons_layout = QVBoxLayout()
        center_buttons_layout.addWidget(self.single_shot_button)
        center_buttons_layout.addWidget(self.continuous_button)
        button_layout.addLayout(center_buttons_layout)

        right_buttons_layout = QVBoxLayout()
        right_buttons_layout.addWidget(self.save_button)
        button_layout.addLayout(right_buttons_layout)

        main_layout.addLayout(button_layout)

        self.setStyleSheet("background-color: #CAD2C5;")
        self.resize_to_screen()

        self.captured_image = None
        self.single_shot_taken = False

    def create_button(self, text, on_click):
        button = QPushButton(text, self)
        button.setStyleSheet(button_style)
        button.clicked.connect(on_click)
        return button

    def create_buttons_layout(self):
        button_layout = QVBoxLayout()
        button_layout.setContentsMargins(100, 0, 50, 50)
        buttons = [
            self.start_button,
            self.stop_button,
            self.single_shot_button,
            self.continuous_button,
            self.save_button,
        ]
        for button in buttons:
            button_layout.addWidget(button)
        return button_layout

    def resize_to_screen(self):
        screen = QApplication.primaryScreen().geometry()
        button_height = screen.height() // 20
        button_width = screen.width() // 4
        self.start_button.setFixedSize(button_width, button_height)
        self.stop_button.setFixedSize(button_width, button_height)
        self.single_shot_button.setFixedSize(button_width, button_height)
        self.continuous_button.setFixedSize(button_width, button_height)
        self.save_button.setFixedSize(button_width, button_height)

        font = QFont()
        font.setPointSize(14)

        buttons = [
            self.start_button,
            self.stop_button,
            self.single_shot_button,
            self.continuous_button,
            self.save_button,
        ]
        for button in buttons:
            button.setFont(font)
    
    def start_camera_handler(self):
        if not self.camera_thread.isRunning():
            self.start_camera()
            if self.single_shot_taken:
                self.save_button.setEnabled(True)
            if not self.camera_thread.continuous_shooting:
                self.continuous_button.setEnabled(True)
            self.camera_thread.frame_ready.connect(self.update_display)
            self.start_button.setEnabled(False)  
        else:
            self.continuous_button.setEnabled(True)
            self.start_recording()



    def start_camera(self):
        self.camera_thread.start()
        self.save_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.single_shot_button.setEnabled(True)

    def stop_camera(self):
        self.camera_thread.stop()
        self.start_button.setEnabled(True)
        self.continuous_button.setEnabled(False)
        self.single_shot_button.setEnabled(False)

        

    def single_shot(self):
        self.captured_image = self.camera_thread.grab_frame()
        if self.captured_image is not None:
            self.save_button.setEnabled(True)
            self.single_shot_taken = True
            self.update_display(self.captured_image)
        else:
            self.save_button.setEnabled(False)  

    def continuous_shot_manager(self):

        self.save_button.setEnabled(False)

        if self.camera_thread.isRunning():
            if not self.camera_thread.continuous_shooting:
                self.camera_thread.set_continuous_shooting(True)
                self.continuous_button.setText('Stop Continuous Shot')
                self.flash_color = '#00FF00'
                self.is_flashing = True
                self.flash_timer.start(400)
                self.stop_button.setEnabled(False)
                self.single_shot_button.setEnabled(False)
                self.start_button.setEnabled(False)
            else:
                self.camera_thread.set_continuous_shooting(False)
                self.continuous_button.setText('Continuous Shot')
                self.is_flashing = False
                self.start_recording()  
                self.continuous_button.setStyleSheet(button_style)
                self.stop_button.setEnabled(True)
                self.single_shot_button.setEnabled(True)
                self.start_button.setEnabled(False)
        else:
            self.start_recording() 

            
    def start_recording(self):
        
        options = QFileDialog.Options()
        file_dialog = QFileDialog()
        file_dialog.setOptions(options)
        file_dialog.setFileMode(QFileDialog.Directory)

        if file_dialog.exec_() == QFileDialog.Accepted:
            selected_dir = file_dialog.selectedFiles()[0]

            today = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            output_dir = os.path.join(selected_dir, today)

            os.makedirs(output_dir, exist_ok=True)

            frames = list(self.buffered_frames.values())[0] 
            for i, frame in enumerate(frames):
                frame_file = os.path.join(output_dir, f"{today}_{i}.png")
                cv2.imwrite(frame_file, cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

            print("Frames saved")

            self.buffered_frames.clear()  
            self.start_camera()  
        else:
            today = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            self.start_camera()
            print("Automatically started recording mode.")


    def save(self):
        options = QFileDialog.Options()
        file_dialog = QFileDialog()
        file_dialog.setOptions(options)
        file_dialog.setFileMode(QFileDialog.AnyFile)

        file_dialog.setNameFilter("PNG (*.png);;JPEG (*.jpg *.jpeg);;All Files (*)")

        if file_dialog.exec_() == QFileDialog.Accepted:
            selected_file = file_dialog.selectedFiles()[0]

            if self.captured_image is not None:
                if file_dialog.selectedNameFilter() == "PNG (*.png)":
                    selected_file += ".png"
                elif file_dialog.selectedNameFilter() == "JPEG (*.jpg *.jpeg)":
                    selected_file += ".jpg"

                cv2.imwrite(selected_file, cv2.cvtColor(self.captured_image, cv2.COLOR_BGR2RGB))
                print("Image saved")

            self.captured_image = None
            self.single_shot_taken = False

            self.save_button.setEnabled(False)

    def update_display(self, frame):
        if frame is not None:
            today = datetime.now().strftime("%Y-%m-%d")  
            self.buffered_frames[today].append(frame)  

            label_width = 800
            label_height = 600

            q_image = QImage(frame.data, frame.shape[1], frame.shape[0], QImage.Format_Grayscale8)
            pixmap = QPixmap.fromImage(q_image.rgbSwapped())
            scaled_pixmap = pixmap.scaled(label_width, label_height, Qt.KeepAspectRatio)

            self.image_label.setPixmap(QPixmap(scaled_pixmap))

    def flash_button(self):
        if self.is_flashing:  
            current_palette = self.continuous_button.palette()
            if current_palette.color(QPalette.Button) == QColor(self.flash_color):
                self.continuous_button.setStyleSheet(button_style)
            else:
              
                self.continuous_button.setStyleSheet(
                    f'background-color: {self.flash_color}; color: white; border: 1px solid #8B3626; border-radius: 5px; padding: 5px 10px;'
                )

class HoverWidget(QWidget):
    def __init__(self, *args, **kwargs):
        super(HoverWidget, self).__init__(*args, **kwargs)
        self.setMouseTracking(True)
        self.setStyleSheet('''
            QWidget {
                background-color: #CAD2C5;
                border-radius: 10px;
            }
            QWidget:hover {
                background-color: #EDE7E3;
            }
            QLabel {
                color: black;
            }
        ''')

    def enterEvent(self, event):
        self.setStyleSheet('''
            QWidget {
                background-color: #EDE7E3;
                border-radius: 10px;
            }
            QLabel {
                color: black;
            }
        ''')

    def leaveEvent(self, event):
        self.setStyleSheet('''
            QWidget {
                background-color: #CAD2C5;
                border-radius: 10px;
            }
            QWidget:hover {
                background-color: #EDE7E3;
            }
            QLabel {
                color: black;
            }
        ''')

class SettingsPage(HoverWidget):
    def __init__(self, camera_thread, parent=None):
        super(SettingsPage, self).__init__(parent)
        self.camera_thread = camera_thread
        self.is_flashing = False 
        self.flash_timer = QTimer(self)
        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout(self)

        self.image_label = QLabel(self)
        self.image_label.setStyleSheet('background-color: #CAD2C5;')

        frame = QFrame(self)
        frame.setStyleSheet('background-color: #CAD2C5;')
        frame_layout = QVBoxLayout(frame)
        frame_layout.setAlignment(Qt.AlignCenter)
        frame_layout.setSpacing(30)

        exposure_fps_groupbox = HoverWidget(self)
        exposure_fps_layout = QVBoxLayout(exposure_fps_groupbox)
        exposure_fps_layout.setSpacing(30)

        exposure_layout = QHBoxLayout()
        self.exposure_label = QLabel('Exposure Value:', self)
        self.exposure_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        exposure_layout.addWidget(self.exposure_label)

        self.exposure_slider = QSlider(Qt.Horizontal)
        self.exposure_slider.setMinimum(1000)
        self.exposure_slider.setMaximum(500000)
        self.exposure_slider.setValue(int(self.camera_thread.exposure_value))
        self.exposure_slider.setTickInterval(5000)
        self.exposure_slider.setTickPosition(QSlider.TicksBelow)
        self.exposure_slider.setFixedWidth(400)
        exposure_layout.addWidget(self.exposure_slider)

        self.exposure_value_label = QLabel(str(self.camera_thread.exposure_value), self)
        self.exposure_value_label.setAlignment(Qt.AlignCenter)
        self.exposure_value_label.setStyleSheet('background-color: #FFFFFF; border: 1px solid #000000; padding: 2px;')
        exposure_layout.addWidget(self.exposure_value_label)

        exposure_fps_layout.addLayout(exposure_layout)

        fps_layout = QHBoxLayout()
        self.fps_label = QLabel(self)
        self.fps_label.setAlignment(Qt.AlignCenter)
        fps_layout.addWidget(self.fps_label)

        exposure_fps_layout.addLayout(fps_layout)

        frame_layout.addWidget(exposure_fps_groupbox)

        trigger_groupbox = HoverWidget(self)
        trigger_layout = QVBoxLayout(trigger_groupbox)
        trigger_layout.setSpacing(10)

        self.trigger_mode_checkbox = QCheckBox("Trigger Mode", self)
        self.trigger_mode_checkbox.setChecked(self.camera_thread.trigger_mode_enabled) 
        self.trigger_mode_checkbox.stateChanged.connect(self.set_trigger_mode)
        self.trigger_mode_checkbox.setStyleSheet('font-size: 20px; ')
        trigger_layout.addWidget(self.trigger_mode_checkbox)

        self.sync_free_run_checkbox = QCheckBox("Sync Free Run", self)
        self.sync_free_run_checkbox.setChecked(False)
        self.sync_free_run_checkbox.stateChanged.connect(self.set_sync_free_run_timer)
        self.sync_free_run_checkbox.setStyleSheet('font-size: 20px; ')
        trigger_layout.addWidget(self.sync_free_run_checkbox)

        sync_free_run_rate_layout = QHBoxLayout()
        self.sync_free_run_rate_label = QLabel("Sync Free Run Trigger Rate:", self)
        self.sync_free_run_rate_spinbox = QSpinBox(self)
        self.sync_free_run_rate_spinbox.setMinimum(1)
        self.sync_free_run_rate_spinbox.setMaximum(50)
        self.sync_free_run_rate_spinbox.setValue(20)
        self.sync_free_run_rate_spinbox.valueChanged.connect(self.set_sync_free_run_timer_rate)
        self.sync_free_run_rate_spinbox.setFixedHeight(50)
        self.sync_free_run_rate_spinbox.setStyleSheet('font-size: 20px; background-color: #EDE7E3')
        sync_free_run_rate_layout.addWidget(self.sync_free_run_rate_label)
        sync_free_run_rate_layout.addWidget(self.sync_free_run_rate_spinbox)

        trigger_layout.addLayout(sync_free_run_rate_layout)

        trigger_source_layout = QHBoxLayout()
        self.trigger_source_label = QLabel("Trigger Source:", self)
        self.trigger_source_combobox = QComboBox(self)
        self.trigger_source_combobox.addItems(["Software", "Line1", "Line3", "Action1"])
        self.trigger_source_combobox.setCurrentText("Line1")
        self.trigger_source_combobox.currentTextChanged.connect(self.set_trigger_source)
        self.trigger_source_combobox.setFixedWidth(800)
        self.trigger_source_combobox.setFixedHeight(50)
        self.trigger_source_combobox.setStyleSheet('font-size: 20px; background-color: #EDE7E3')
        trigger_source_layout.addWidget(self.trigger_source_label)
        trigger_source_layout.addWidget(self.trigger_source_combobox)

        trigger_layout.addLayout(trigger_source_layout)

        frame_layout.addWidget(trigger_groupbox)

        main_layout.addWidget(self.image_label)
        main_layout.addWidget(frame)

        self.camera_thread.frame_ready.connect(self.update_display)
        self.camera_thread.fps_changed.connect(self.update_fps)

        self.exposure_slider.valueChanged.connect(self.set_exposure_value)

        font = QFont()
        font.setPointSize(16)

        labels = [
            self.exposure_label,
            self.exposure_value_label,
            self.fps_label,
            self.sync_free_run_rate_label,
            self.trigger_source_label
        ]
        for label in labels:
            label.setFont(font)

        execute_button = self.create_button('Execute', self.execute_sync_free_run_timer_update)
        execute_button.setFont(QFont("Arial", 16))  
        frame_layout.addWidget(execute_button)
        self.save_button_settings = self.create_button('Save', self.save_settings)
        self.save_button_settings.setEnabled(True)  
        self.save_button_settings.setStyleSheet(button_style)
        self.save_button_settings.setFont(QFont("Arial", 16))  
        frame_layout.addWidget(self.save_button_settings)

        self.flash_timer.timeout.connect(self.flash_button)

        

    def start_camera_handler(self):
        if not self.camera_thread.isRunning():
            self.start_camera()
            if not self.camera_thread.continuous_shooting:
                self.continuous_button.setEnabled(True)
            self.camera_thread.frame_ready.connect(self.update_display)

        else:
            self.trigger_mode_checkbox.setEnabled(False)
            self.continuous_button.setEnabled(True)


    def start_camera(self):
        self.camera_thread.start()
        
        

    def create_button(self, text, on_click):
        button = QPushButton(text, self)
        button.setStyleSheet(button_style)
        button.clicked.connect(on_click)
        button.setFixedHeight(60)
        return button

    def save_settings(self):
        if self.camera_thread.grab_frame() is not None:
            print("Settings Page settings saved.")
            self.save_button_settings.setEnabled(False)
            QMessageBox.information(self, "Settings Saved", "Settings have been saved successfully.")
        else:
            QMessageBox.warning(self, "No Image", "Cannot save settings without grabbing an image from the camera.")

    def execute_sync_free_run_timer_update(self):
        self.camera_thread.sync_free_run_timer_update_execute()

    def update_display(self, frame):
        if frame is not None:
            label_width = 800
            label_height = 600

            q_image = QImage(frame.data, frame.shape[1], frame.shape[0], QImage.Format_Grayscale8)
            pixmap = QPixmap.fromImage(q_image.rgbSwapped())

            self.image_label.setPixmap(pixmap.scaled(label_width, label_height, Qt.KeepAspectRatio))

    def update_fps(self, fps):
        self.fps_label.setText(f"FPS: {fps:.1f}")

    def set_exposure_value(self, value):
        self.camera_thread.set_exposure_value(value)
        self.exposure_value_label.setText(str(value))

    def set_trigger_mode(self, state):
        if self.camera_thread.isRunning():
            if state == Qt.Checked:
                self.camera_thread.set_trigger_mode(True)
            else:
                self.camera_thread.set_trigger_mode(False)

    def set_sync_free_run_timer(self, state):
        if state == Qt.Checked:
            self.camera_thread.set_sync_free_run_timer(True)
        else:
            self.camera_thread.set_sync_free_run_timer(False)

    def set_sync_free_run_timer_rate(self):
        rate = self.sync_free_run_rate_spinbox.value()
        self.camera_thread.set_sync_free_run_timer_rate(rate)

    def set_trigger_source(self, source):
        self.camera_thread.set_trigger_source(source)

    def flash_button(self):
        if self.is_flashing:
            current_palette = self.save_button_settings.palette()
            if current_palette.color(QPalette.Button) == QColor(self.flash_color):
                self.save_button_settings.setStyleSheet(button_style)
            else:
                self.save_button_settings.setStyleSheet(
                    f'background-color: {self.flash_color}; color: white; border: 1px solid #8B3626; border-radius: 5px; padding: 5px 10px;'
                )

    def start_flashing(self, color='#FF0000'):
        self.is_flashing = True
        self.flash_color = color
        self.flash_timer.start(300)

    def stop_flashing(self):
        self.is_flashing = False
        self.flash_timer.stop()


class HelpPage(HoverWidget):
    def __init__(self, parent=None):
        super(HelpPage, self).__init__(parent)
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignCenter)

        help_label = QLabel("Welcome to Camera App Help Page", self)
        help_label.setAlignment(Qt.AlignCenter)
        help_label.setStyleSheet('font-size: 24px;')

        instructions_label = QLabel(
            "hello."
            "\n\nworld"
            "\n\nThe 'dsgh"
            "\n\nTredfghjk."
            "\n\nrtfyjk!"
            , self)
        instructions_label.setAlignment(Qt.AlignCenter)
        instructions_label.setStyleSheet('font-size: 18px;')
        instructions_label.setWordWrap(True)

        main_layout.addWidget(help_label)
        main_layout.addWidget(instructions_label)


class CameraApp(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Camera Application")
        self.setGeometry(100, 100, 800, 600)
        self.setFixedSize(1600, 900)
        self.setStyleSheet("background-color: #CAD2C5;")

        self.camera_thread = CameraThread()
        self.main_page = MainPage(self.camera_thread)
        self.settings_page = SettingsPage(self.camera_thread)
        self.help_page = HelpPage()  

        self.tab_widget = QTabWidget(self)
        self.tab_widget.addTab(self.main_page, "Main")
        self.tab_widget.addTab(self.settings_page, "Settings")
        self.tab_widget.addTab(self.help_page, "Help") 
        self.tab_widget.setStyleSheet(
            '''
            QTabWidget::pane {
                border-top: 2px solid #CAD2C5;
            }
            QTabWidget::tab-bar {
                left: 20px;
            }
            QTabBar::tab {
                background: #354F52;
                color: white;
                border: 2px solid #2F3E46;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                min-width: 80px;
                padding: 8px;
            }
            QTabBar::tab:selected {
                background: #A0522D;
                color: white;
                border: 2px solid #8B3626;
                border-bottom-color: #A0522D;
            }
            '''
        )

        layout = QVBoxLayout(self)
        layout.addWidget(self.tab_widget)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = CameraApp()
    window.show()
    sys.exit(app.exec_())
