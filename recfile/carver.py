import os
import threading
import struct
from utils import analyze_boot_sector

class Carver(threading.Thread):
    def __init__(self, source_path, output_dir, file_types, progress_callback=None, found_callback=None, finished_callback=None, error_callback=None):
        super().__init__()
        self.source_path = source_path
        self.output_dir = output_dir
        self.file_types = file_types # dict of types to recover e.g. {'jpg': True, 'png': True}
        self.progress_callback = progress_callback
        self.found_callback = found_callback
        self.finished_callback = finished_callback
        self.error_callback = error_callback
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set() # Start in running (not paused) state

        # Signatures
        self.signatures = {
            'jpg': {
                'header': b'\xFF\xD8\xFF',
                'footer': b'\xFF\xD9',
                'max_size': 10 * 1024 * 1024 # 10 MB
            },
            'png': {
                'header': b'\x89\x50\x4E\x47\x0D\x0A\x1A\x0A',
                'footer': b'\x49\x45\x4E\x44\xAE\x42\x60\x82',
                'max_size': 20 * 1024 * 1024 # 20 MB
            },
            'pdf': {
                'header': b'%PDF-',
                'footer': b'%%EOF',
                'max_size': 50 * 1024 * 1024 # 50 MB
            },
            'zip': { # Also covers docx, xlsx
                'header': b'\x50\x4B\x03\x04',
                'footer': b'\x50\x4B\x05\x06',
                'max_size': 100 * 1024 * 1024 # 100 MB
            }
        }

    def run(self):
        try:
            # Специфичная поддержка FAT32/NTFS: анализ размера кластера для оптимизации (выравнивания)
            boot_info = analyze_boot_sector(self.source_path)
            cluster_size = boot_info.get('cluster_size', 512)
            fs_type = boot_info.get('fs_type', 'Unknown')
            print(f"[Info] FS: {fs_type}, Cluster Size: {cluster_size} bytes")

            total_size = 0
            if not self.source_path.startswith(r"\\.\PhysicalDrive"):
                try:
                    total_size = os.path.getsize(self.source_path)
                except:
                    pass

            os.makedirs(self.output_dir, exist_ok=True)
            recovered_counts = {k: 0 for k in self.signatures}
            
            with open(self.source_path, "rb") as f_in:
                # Seek to find total size of physical drives if needed
                if total_size == 0:
                    try:
                        f_in.seek(0, os.SEEK_END)
                        total_size = f_in.tell()
                        f_in.seek(0)
                    except:
                        pass

                offset = 0
                chunk_size = 1024 * 1024 * 2 # 2 MB search chunks
                overlap = 1024 # Overlap for signatures

                while not self._stop_event.is_set():
                    # Handle pause state
                    self._pause_event.wait()
                    if self._stop_event.is_set():
                        break

                    f_in.seek(offset)
                    chunk = f_in.read(chunk_size + overlap)
                    if not chunk:
                        break # EOF

                    # Find the earliest header match in this chunk to prevent skipping files
                    earliest_idx = -1
                    earliest_ext = None

                    for ext, sig_data in self.signatures.items():
                         # Если ищем zip или docx, проверяем zip заголовок
                         if ext == 'zip' and (self.file_types.get('zip', False) or self.file_types.get('docx', False)):
                             pass
                         elif not self.file_types.get(ext, False):
                             continue
                         
                         header = sig_data['header']
                         idx = 0
                         while True:
                             idx = chunk.find(header, idx)
                             if idx == -1:
                                 break
                             
                             global_offset = offset + idx
                             # Sector alignment
                             if global_offset % 512 != 0:
                                 idx += 1
                                 continue
                             
                             if earliest_idx == -1 or idx < earliest_idx:
                                 earliest_idx = idx
                                 earliest_ext = ext
                             break # Check next extension

                    if earliest_idx == -1:
                        # No header found, advance offset
                        offset += chunk_size
                        if self.progress_callback:
                            self.progress_callback(offset, total_size)
                        continue

                    # Process the header found at earliest_idx
                    ext = earliest_ext
                    sig_data = self.signatures[ext]
                    global_offset = offset + earliest_idx

                    # Read up to max_size bytes for parsing
                    max_size = sig_data['max_size']
                    f_in.seek(global_offset)
                    candidate_data = f_in.read(max_size)

                    file_size = -1

                    if ext == 'png':
                        footer = sig_data['footer']
                        f_idx = candidate_data.find(footer)
                        if f_idx != -1:
                            file_size = f_idx + len(footer)

                    elif ext == 'jpg':
                        # To avoid Exif thumbnails, search for next sector-aligned JPG header and find last footer before it
                        next_header_idx = -1
                        search_idx = 4
                        while True:
                            h_idx = candidate_data.find(b'\xFF\xD8\xFF', search_idx)
                            if h_idx == -1:
                                break
                            if (global_offset + h_idx) % 512 == 0:
                                next_header_idx = h_idx
                                break
                            search_idx = h_idx + 1

                        if next_header_idx != -1:
                            f_idx = candidate_data.rfind(b'\xFF\xD9', 4, next_header_idx)
                            if f_idx != -1:
                                file_size = f_idx + 2
                            else:
                                file_size = next_header_idx
                        else:
                            f_idx = candidate_data.rfind(b'\xFF\xD9', 4)
                            if f_idx != -1:
                                file_size = f_idx + 2

                    elif ext == 'pdf':
                        # Find next sector-aligned PDF header and get last %%EOF before it
                        next_header_idx = -1
                        search_idx = 5
                        while True:
                            h_idx = candidate_data.find(b'%PDF-', search_idx)
                            if h_idx == -1:
                                break
                            if (global_offset + h_idx) % 512 == 0:
                                next_header_idx = h_idx
                                break
                            search_idx = h_idx + 1

                        if next_header_idx != -1:
                            f_idx = candidate_data.rfind(b'%%EOF', 5, next_header_idx)
                        else:
                            f_idx = candidate_data.rfind(b'%%EOF', 5)

                        if f_idx != -1:
                            file_size = f_idx + 5
                            # Include trailing newlines/carriage returns
                            while file_size < len(candidate_data) and candidate_data[file_size] in (b'\r'[0], b'\n'[0]):
                                file_size += 1

                    elif ext == 'zip':
                        # Local ZIP headers aren't sector-aligned, but a new ZIP archive usually is.
                        # Find next sector-aligned ZIP header b'\x50\x4B\x03\x04'
                        next_header_idx = -1
                        search_idx = 4
                        while True:
                            h_idx = candidate_data.find(b'\x50\x4B\x03\x04', search_idx)
                            if h_idx == -1:
                                break
                            if (global_offset + h_idx) % 512 == 0:
                                next_header_idx = h_idx
                                break
                            search_idx = h_idx + 1

                        if next_header_idx != -1:
                            f_idx = candidate_data.find(b'\x50\x4B\x05\x06', 4, next_header_idx)
                        else:
                            f_idx = candidate_data.find(b'\x50\x4B\x05\x06', 4)

                        if f_idx != -1:
                            if f_idx + 22 <= len(candidate_data):
                                comment_len = struct.unpack('<H', candidate_data[f_idx+20 : f_idx+22])[0]
                                file_size = f_idx + 22 + comment_len
                            else:
                                file_size = f_idx + 22

                    # Recover file if file_size is valid
                    if file_size != -1 and file_size <= len(candidate_data):
                        file_data = candidate_data[:file_size]
                        
                        actual_ext = ext
                        save_file = True
                        
                        if ext == 'zip':
                            import zipfile
                            import io
                            is_docx = False
                            try:
                                with zipfile.ZipFile(io.BytesIO(file_data), 'r') as z:
                                    if 'word/document.xml' in z.namelist():
                                        is_docx = True
                            except:
                                pass
                                
                            if is_docx:
                                if self.file_types.get('docx', False):
                                    actual_ext = 'docx'
                                elif not self.file_types.get('zip', False):
                                    save_file = False
                            else:
                                if not self.file_types.get('zip', False):
                                    save_file = False
                        
                        if not save_file:
                            offset = global_offset + file_size
                            continue

                        recovered_counts[actual_ext] = recovered_counts.get(actual_ext, 0) + 1
                        file_name = f"recovered_{recovered_counts[actual_ext]}.{actual_ext}"
                        file_path = os.path.join(self.output_dir, file_name)
                        
                        status = "Успешно"
                        try:
                            with open(file_path, "wb") as out_f:
                                out_f.write(file_data)
                        except Exception as e:
                            status = "Ошибка записи"
                            
                        if self.found_callback:
                            self.found_callback(file_path, actual_ext, file_size, global_offset, status)

                        offset = global_offset + file_size
                    else:
                        # Skip this sector and keep searching
                        offset = global_offset + 512

                    if self.progress_callback:
                        self.progress_callback(offset, total_size)
                        
            if not self._stop_event.is_set() and self.finished_callback:
                self.finished_callback()
            elif self.error_callback:
                self.error_callback("Восстановление остановлено.")

        except PermissionError:
            if self.error_callback:
                self.error_callback("Ошибка доступа. Убедитесь, что программа запущена от имени Администратора.")
        except Exception as e:
            if self.error_callback:
                self.error_callback(f"Ошибка при восстановлении: {e}")

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    def stop(self):
        self._stop_event.set()
        self._pause_event.set() # Unblock waiting threads

