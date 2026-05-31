import ctypes
import os
import subprocess
import struct

def get_drives():
    """
    Возвращает список физических и логических дисков в Windows.
    """
    drives = []
    
    # Физические диски
    try:
        output = subprocess.check_output(
            ["wmic", "diskdrive", "get", "DeviceID,Model,Size", "/format:csv"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            text=True
        )
        lines = output.strip().split('\n')
        for line in lines[1:]: 
            if not line.strip():
                continue
            parts = line.strip().split(',')
            if len(parts) >= 4:
                device_id = parts[1].strip()
                model = parts[2].strip()
                size_str = parts[3].strip()
                try:
                    size_gb = round(int(size_str) / (1024**3), 2)
                    label = f"{model} ({size_gb} GB)"
                except ValueError:
                    label = model
                
                drives.append({
                    'path': device_id,
                    'label': label,
                    'is_physical': True
                })
    except Exception as e:
        print(f"Ошибка при получении физических дисков: {e}")
        for i in range(4):
            path = rf"\\.\PhysicalDrive{i}"
            try:
                with open(path, "rb") as f:
                    drives.append({
                        'path': path,
                        'label': f"Physical Drive {i}",
                        'is_physical': True
                    })
            except Exception:
                pass
                
    # Логические диски
    try:
        output = subprocess.check_output(
            ["wmic", "logicaldisk", "get", "DeviceID,VolumeName,Size", "/format:csv"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            text=True
        )
        lines = output.strip().split('\n')
        for line in lines[1:]:
            if not line.strip(): continue
            parts = line.strip().split(',')
            if len(parts) >= 4:
                device_id = parts[1].strip()
                volume_name = parts[2].strip()
                size_str = parts[3].strip()
                try:
                    size_gb = round(int(size_str) / (1024**3), 2)
                    label = f"Логический {device_id} {volume_name} ({size_gb} GB)"
                except ValueError:
                    label = f"Логический {device_id} {volume_name}"
                
                drives.append({
                    'path': rf"\\.\{device_id}",
                    'label': label,
                    'is_physical': False
                })
    except Exception as e:
        print(f"Ошибка при получении логических дисков: {e}")

    return drives
def is_admin():
    """Проверяет, запущен ли скрипт с правами администратора."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False
def analyze_boot_sector(drive_path):
    """
    Анализирует загрузочный сектор диска/образа.
    Поддерживает:
    1. Использование Win32 API для логических дисков (GetVolumeInformationW, GetDiskFreeSpaceW).
    2. Чтение VBR (Volume Boot Record) напрямую (для разделов/образов разделов).
    3. Чтение MBR (Master Boot Record) и переход к первому разделу.
    4. Чтение GPT (GUID Partition Table) и переход к первому разделу.
    """
    info = {
        'fs_type': 'Unknown',
        'bytes_per_sector': 512,
        'sectors_per_cluster': 1,
        'cluster_size': 512
    }
    
    # 1. Пробуем определить через Win32 API, если это логический диск (например C: или \\.\C:)
    import re
    match = re.match(r'^(?:\\\\\.\\)?([A-Za-z]):\\*$', drive_path)
    is_logical = False
    if match:
        try:
            if not os.path.isfile(drive_path):
                is_logical = True
        except Exception:
            is_logical = True
            
    if is_logical:
        drive_letter = match.group(1) + ":\\"
        try:
            buf = ctypes.create_unicode_buffer(1024)
            rc = ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(drive_letter),
                None, 0, None, None, None,
                buf, ctypes.sizeof(buf)
            )
            if rc and buf.value:
                fs = buf.value.upper()
                if fs in ('NTFS', 'FAT32'):
                    info['fs_type'] = fs
                    
                    # Получаем информацию о кластерах
                    spc = ctypes.c_ulong(0)
                    bps = ctypes.c_ulong(0)
                    rc_space = ctypes.windll.kernel32.GetDiskFreeSpaceW(
                        ctypes.c_wchar_p(drive_letter),
                        ctypes.byref(spc),
                        ctypes.byref(bps),
                        ctypes.byref(ctypes.c_ulong(0)),
                        ctypes.byref(ctypes.c_ulong(0))
                    )
                    if rc_space:
                        info['bytes_per_sector'] = bps.value
                        info['sectors_per_cluster'] = spc.value
                        info['cluster_size'] = bps.value * spc.value
                    return info
        except Exception as api_err:
            print(f"Win32 API error for {drive_letter}: {api_err}")

    def parse_vbr(sector):
        if len(sector) < 512 or sector[510:512] != b'\x55\xaa': return False
        try:
            bytes_per_sector = struct.unpack('<H', sector[11:13])[0]
            sectors_per_cluster = sector[13]
            if bytes_per_sector in (512, 1024, 2048, 4096) and sectors_per_cluster > 0:
                info['bytes_per_sector'] = bytes_per_sector
                info['sectors_per_cluster'] = sectors_per_cluster
                info['cluster_size'] = bytes_per_sector * sectors_per_cluster
                
                # NTFS VBR signature is "NTFS    "
                if sector[3:11] == b'NTFS    ':
                    info['fs_type'] = 'NTFS'
                    return True
                # FAT32 VBR signature is "FAT32   "
                elif sector[82:90] == b'FAT32   ':
                    info['fs_type'] = 'FAT32'
                    return True
        except: pass
        return False

    try:
        with open(drive_path, "rb") as f:
            boot_sector = f.read(512)
            
        if len(boot_sector) < 512 or boot_sector[510:512] != b'\x55\xaa':
            return info
            
        # 2. Сначала пробуем парсить как VBR (например, логический диск или образ одного раздела)
        if parse_vbr(boot_sector):
            return info
            
        # 3. Пробуем парсить как GPT (GUID Partition Table)
        # GPT Header находится в LBA 1 (байт 512)
        try:
            with open(drive_path, "rb") as f:
                f.seek(512)
                gpt_header = f.read(92)
            if len(gpt_header) == 92 and gpt_header[0:8] == b'EFI PART':
                part_lba = struct.unpack('<Q', gpt_header[72:80])[0]
                num_parts = struct.unpack('<I', gpt_header[80:84])[0]
                part_size = struct.unpack('<I', gpt_header[84:88])[0]
                
                # Читаем записи разделов (ограничимся первыми 32 записями для безопасности)
                read_parts = min(num_parts, 32)
                with open(drive_path, "rb") as f:
                    f.seek(part_lba * 512)
                    entries_data = f.read(read_parts * part_size)
                
                for i in range(read_parts):
                    offset = i * part_size
                    entry = entries_data[offset : offset + part_size]
                    if len(entry) < part_size:
                        break
                    # Если GUID типа раздела пустой, то запись не используется
                    type_guid = entry[0:16]
                    if type_guid == b'\x00' * 16:
                        continue
                    
                    start_lba = struct.unpack('<Q', entry[32:40])[0]
                    if start_lba > 0:
                        with open(drive_path, "rb") as f:
                            f.seek(start_lba * 512)
                            vbr_sector = f.read(512)
                        if parse_vbr(vbr_sector):
                            return info
        except Exception as gpt_err:
            print(f"Ошибка парсинга GPT: {gpt_err}")

        # 4. Если это MBR физического диска
        part_type = boot_sector[450] # тип первого раздела
        if part_type in (0x07, 0x0B, 0x0C, 0x0E, 0x0F):
            lba_start = struct.unpack('<I', boot_sector[454:458])[0]
            if lba_start > 0:
                with open(drive_path, "rb") as f:
                    f.seek(lba_start * 512)
                    vbr_sector = f.read(512)
                parse_vbr(vbr_sector)
                
    except Exception as e:
        print(f"Ошибка чтения boot sector: {e}")
        
    return info
