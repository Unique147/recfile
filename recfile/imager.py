import os
import threading

class Imager(threading.Thread):
    def __init__(self, source_path, dest_path, progress_callback=None, finished_callback=None, error_callback=None):
        super().__init__()
        self.source_path = source_path
        self.dest_path = dest_path
        self.progress_callback = progress_callback
        self.finished_callback = finished_callback
        self.error_callback = error_callback
        self._stop_event = threading.Event()

    def run(self):
        try:
            # Check if source_path is a directory (folder)
            is_folder = os.path.isdir(self.source_path)
            
            if is_folder:
                # Get list of all files in the directory recursively
                file_list = []
                total_size = 0
                for root, dirs, files in os.walk(self.source_path):
                    for file in files:
                        full_path = os.path.join(root, file)
                        try:
                            sz = os.path.getsize(full_path)
                            file_list.append((full_path, sz))
                            # Pad size to 512 bytes
                            padded_sz = ((sz + 511) // 512) * 512
                            total_size += padded_sz
                        except:
                            pass
                
                bytes_written = 0
                with open(self.dest_path, "wb") as f_out:
                    for full_path, sz in file_list:
                        if self._stop_event.is_set():
                            break
                        
                        try:
                            with open(full_path, "rb") as f_in:
                                # Read and write in blocks of 64KB
                                while not self._stop_event.is_set():
                                    chunk = f_in.read(1024 * 64)
                                    if not chunk:
                                        break
                                    f_out.write(chunk)
                                    bytes_written += len(chunk)
                                    if self.progress_callback:
                                        self.progress_callback(bytes_written, total_size)
                            
                            # Padding to 512-byte sector boundary
                            padding_needed = 512 - (sz % 512)
                            if padding_needed < 512:
                                f_out.write(b'\x00' * padding_needed)
                                bytes_written += padding_needed
                                if self.progress_callback:
                                    self.progress_callback(bytes_written, total_size)
                        except Exception as e:
                            print(f"Error copying {full_path}: {e}")
                            
            else:
                # Source is a file or physical disk
                total_size = 0
                is_win_physical = self.source_path.startswith(r"\\.\PhysicalDrive")
                is_linux_block = self.source_path.startswith("/dev/")
                if not (is_win_physical or is_linux_block):
                    try:
                        total_size = os.path.getsize(self.source_path)
                    except:
                        pass
                
                chunk_size = 1024 * 1024 * 4 # 4 MB chunks
                bytes_read_total = 0
                
                with open(self.source_path, "rb") as f_in:
                    # Seek to find total size of physical drives if needed
                    if total_size == 0:
                        try:
                            f_in.seek(0, os.SEEK_END)
                            total_size = f_in.tell()
                            f_in.seek(0)
                        except:
                            pass

                    with open(self.dest_path, "wb") as f_out:
                        while not self._stop_event.is_set():
                            chunk = f_in.read(chunk_size)
                            if not chunk:
                                break # End of file/disk
                            
                            f_out.write(chunk)
                            bytes_read_total += len(chunk)
                            
                            if self.progress_callback:
                                self.progress_callback(bytes_read_total, total_size)
                                
            if not self._stop_event.is_set():
                if self.finished_callback:
                    self.finished_callback()
            else:
                if self.error_callback:
                    self.error_callback("Операция отменена пользователем.")
                    
        except PermissionError:
            if self.error_callback:
                self.error_callback("Ошибка доступа. Убедитесь, что программа запущена от имени Администратора.")
        except Exception as e:
            if self.error_callback:
                self.error_callback(f"Ошибка при создании образа: {e}")

    def stop(self):
        self._stop_event.set()

