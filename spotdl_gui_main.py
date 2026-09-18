"""
SpotDL GUI - A beautiful desktop application for downloading Spotify playlists
"""

import sys
import os
import json
import threading
from pathlib import Path
from datetime import datetime

import PyQt6.QtWidgets as QW
import PyQt6.QtCore as QC
import PyQt6.QtGui as QG
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QRect
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QProgressBar, QTextEdit,
    QFileDialog, QComboBox, QCheckBox, QSpinBox, QTabWidget,
    QListWidget, QListWidgetItem, QMessageBox, QGroupBox,
    QGridLayout, QSplitter, QStatusBar
)

try:
    from spotdl import Spotdl
    from spotdl.types.song import Song
except ImportError:
    print("Error: spotdl not installed. Install with: pip install spotdl yt-dlp")
    sys.exit(1)


class DownloadWorker(QThread):
    """Worker thread for downloads to keep UI responsive"""
    progress = pyqtSignal(str)  # Log message
    progress_bar = pyqtSignal(int)  # Progress percentage
    finished = pyqtSignal(bool)  # Success/failure
    status_update = pyqtSignal(str)  # Current status
    
    def __init__(self, urls, output_path, settings):
        super().__init__()
        self.urls = urls
        self.output_path = output_path
        self.settings = settings
        self.is_running = True
    
    def run(self):
        try:
            self.progress.emit(f"[{datetime.now().strftime('%H:%M:%S')}] Starting download...\n")
            
            # Create spotdl instance
            spotdl = Spotdl(
                client_id="",
                client_secret="",
                user_auth=False,
                cache_path=os.path.join(self.output_path, ".spotdl"),
                config=None,
                output=os.path.join(self.output_path, self.settings['output_format'])
            )
            
            total_urls = len(self.urls)
            for idx, url in enumerate(self.urls):
                if not self.is_running:
                    break
                
                try:
                    self.status_update.emit(f"Downloading ({idx + 1}/{total_urls}): {url}")
                    self.progress.emit(f"[{datetime.now().strftime('%H:%M:%S')}] Processing: {url}\n")
                    
                    # Download the URL
                    songs = spotdl.download_song(url)
                    if songs:
                        self.progress.emit(f"✓ Successfully downloaded: {songs[0].name if isinstance(songs, list) else songs.name}\n")
                    
                    progress_pct = int((idx + 1) / total_urls * 100)
                    self.progress_bar.emit(progress_pct)
                    
                except Exception as e:
                    self.progress.emit(f"✗ Error downloading {url}: {str(e)}\n")
            
            self.progress.emit(f"\n[{datetime.now().strftime('%H:%M:%S')}] Download complete!\n")
            self.status_update.emit("Ready")
            self.finished.emit(True)
            
        except Exception as e:
            self.progress.emit(f"\n[{datetime.now().strftime('%H:%M:%S')}] ERROR: {str(e)}\n")
            self.status_update.emit("Error")
            self.finished.emit(False)
    
    def stop(self):
        self.is_running = False


class SpotDLGUI(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SpotDL - Spotify Downloader")
        self.setGeometry(100, 100, 1000, 700)
        
        # Settings
        self.output_path = str(Path.home() / "Music" / "SpotDL Downloads")
        self.download_worker = None
        self.settings = {
            'output_format': '{artist} - {title}.mp3',
            'skip_existing': True,
            'ffmpeg_path': 'auto'
        }
        
        self.init_ui()
        self.load_settings()
        
    def init_ui(self):
        """Initialize the user interface"""
        central_widget = QW.QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QW.QVBoxLayout(central_widget)
        
        # Create tabs
        tabs = QTabWidget()
        
        # Download tab
        download_widget = self.create_download_tab()
        tabs.addTab(download_widget, "Download")
        
        # Settings tab
        settings_widget = self.create_settings_tab()
        tabs.addTab(settings_widget, "Settings")
        
        main_layout.addWidget(tabs)
        
        # Status bar
        self.statusBar().showMessage("Ready")
    
    def create_download_tab(self):
        """Create the download tab"""
        widget = QW.QWidget()
        layout = QW.QVBoxLayout(widget)
        
        # Title
        title = QLabel("Spotify Playlist Downloader")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #1DB954;")
        layout.addWidget(title)
        
        # URL input
        url_group = QGroupBox("Spotify URL")
        url_layout = QW.QVBoxLayout()
        
        url_label = QLabel("Paste Spotify playlist, album, or song URL:")
        url_layout.addWidget(url_label)
        
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://open.spotify.com/playlist/...")
        url_layout.addWidget(self.url_input)
        
        url_group.setLayout(url_layout)
        layout.addWidget(url_group)
        
        # Output folder
        folder_group = QGroupBox("Output Location")
        folder_layout = QW.QHBoxLayout()
        
        self.folder_label = QLabel(self.output_path)
        self.folder_label.setWordWrap(True)
        folder_layout.addWidget(self.folder_label)
        
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_folder)
        folder_layout.addWidget(browse_btn)
        
        folder_group.setLayout(folder_layout)
        layout.addWidget(folder_group)
        
        # Progress
        progress_group = QGroupBox("Progress")
        progress_layout = QW.QVBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("Ready")
        progress_layout.addWidget(self.status_label)
        
        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)
        
        # Buttons
        button_layout = QW.QHBoxLayout()
        
        self.download_btn = QPushButton("Download")
        self.download_btn.setStyleSheet("""
            QPushButton {
                background-color: #1DB954;
                color: white;
                padding: 10px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1ed760;
            }
        """)
        self.download_btn.clicked.connect(self.start_download)
        button_layout.addWidget(self.download_btn)
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_download)
        button_layout.addWidget(self.stop_btn)
        
        self.open_folder_btn = QPushButton("Open Folder")
        self.open_folder_btn.clicked.connect(self.open_output_folder)
        button_layout.addWidget(self.open_folder_btn)
        
        layout.addLayout(button_layout)
        
        # Log output
        log_group = QGroupBox("Activity Log")
        log_layout = QW.QVBoxLayout()
        
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(200)
        self.log_output.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #00ff00;
                font-family: 'Courier New';
                font-size: 10px;
            }
        """)
        log_layout.addWidget(self.log_output)
        
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        layout.addStretch()
        return widget
    
    def create_settings_tab(self):
        """Create the settings tab"""
        widget = QW.QWidget()
        layout = QW.QVBoxLayout(widget)
        
        title = QLabel("Settings")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)
        
        # Output format
        format_group = QGroupBox("Output Format")
        format_layout = QW.QVBoxLayout()
        
        format_label = QLabel("Filename template:")
        format_layout.addWidget(format_label)
        
        self.format_input = QLineEdit()
        self.format_input.setText(self.settings['output_format'])
        format_layout.addWidget(self.format_input)
        
        format_help = QLabel("Variables: {artist}, {title}, {album}, {date}")
        format_help.setStyleSheet("color: gray; font-size: 10px;")
        format_layout.addWidget(format_help)
        
        format_group.setLayout(format_layout)
        layout.addWidget(format_group)
        
        # Behavior options
        behavior_group = QGroupBox("Download Behavior")
        behavior_layout = QW.QVBoxLayout()
        
        self.skip_checkbox = QCheckBox("Skip existing files")
        self.skip_checkbox.setChecked(self.settings['skip_existing'])
        behavior_layout.addWidget(self.skip_checkbox)
        
        behavior_group.setLayout(behavior_layout)
        layout.addWidget(behavior_group)
        
        # Save/Reset buttons
        button_layout = QW.QHBoxLayout()
        
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self.save_settings)
        button_layout.addWidget(save_btn)
        
        reset_btn = QPushButton("Reset to Default")
        reset_btn.clicked.connect(self.reset_settings)
        button_layout.addWidget(reset_btn)
        
        layout.addLayout(button_layout)
        layout.addStretch()
        
        return widget
    
    def browse_folder(self):
        """Open folder browser"""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Output Folder",
            self.output_path
        )
        if folder:
            self.output_path = folder
            self.folder_label.setText(self.output_path)
    
    def start_download(self):
        """Start the download process"""
        url = self.url_input.text().strip()
        
        if not url:
            QMessageBox.warning(self, "Input Error", "Please enter a Spotify URL")
            return
        
        if not os.path.exists(self.output_path):
            try:
                os.makedirs(self.output_path)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Cannot create folder: {str(e)}")
                return
        
        self.download_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.url_input.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log_output.clear()
        
        urls = [url]
        self.download_worker = DownloadWorker(urls, self.output_path, self.settings)
        self.download_worker.progress.connect(self.update_log)
        self.download_worker.progress_bar.connect(self.update_progress)
        self.download_worker.finished.connect(self.on_download_finished)
        self.download_worker.status_update.connect(self.update_status)
