import spidev
import time
import os
import subprocess

# --- AUTOMATIC HOOKS & SYSTEM DIRECTORY VALIDATION ---
def safe_init_gpio(pin):
    pin_path = f"/sys/class/gpio/gpio{pin}"
    if not os.path.exists(pin_path):
        try:
            with open("/sys/class/gpio/export", "w") as f: f.write(str(pin))
            time.sleep(0.05)
        except Exception: pass
    while not os.path.exists(f"{pin_path}/direction"):
        time.sleep(0.01)
    with open(f"{pin_path}/direction", "w") as f: f.write("out")

safe_init_gpio(56)
safe_init_gpio(57)

# --- START THE OPERATIONAL SPI PORT ---
spi = spidev.SpiDev()
spi.open(0, 0)
spi.max_speed_hz = 60000000  # 60MHz max bandwidth (1.9ms wire transfer time)
spi.mode = 0

def set_dc(val):
    with open('/sys/class/gpio/gpio57/value', 'w') as f: f.write(str(val))
def set_rst(val):
    with open('/sys/class/gpio/gpio56/value', 'w') as f: f.write(str(val))
def write_cmd(cmd):
    set_dc(0)
    spi.xfer2([cmd])
def write_data(data_bytes):
    set_dc(1)
    for i in range(0, len(data_bytes), 4096):
        spi.xfer2(list(data_bytes[i:i+4096]))

# Hard physical line reset pulse
set_rst(0); time.sleep(0.05); set_rst(1); time.sleep(0.05)
write_cmd(0x01); time.sleep(0.05) # Reset
write_cmd(0x11); time.sleep(0.05) # Wake

# Configure verified un-mirrored layout parameters
write_cmd(0x36); write_data(b'\x40')
write_cmd(0x21)                                  # Hardware Color Inversion ON
write_cmd(0x3A); write_data(b'\x05')             # 16-bit RGB565 Layout

# WIPE PANEL MEMORY CLEAN (Clears out the noise chin permanently)
write_cmd(0x2A); write_data(b'\x00\x00\x00\xEF') # Columns (0 to 239)
write_cmd(0x2B); write_data(b'\x00\x00\x01\x3F') # Select full 320 row canvas
write_cmd(0x2C)                                  # Open RAM Write
write_data(b'\x00' * (240 * 320 * 2))           # Flood the chip memory with deep black

# --- EQUAL BORDER POSITIONING: 40px TOP BORDER & 40px BOTTOM BORDER ---
# Columns (0 to 239) -> Hex: 0x0000 to 0x00EF
write_cmd(0x2A); write_data(b'\x00\x00\x00\xEF')
# Start at Row 40 (Hex: 0x0028) and terminate right at Row 279 (Hex: 0x0117)
write_cmd(0x2B); write_data(b'\x00\x28\x01\x17')
write_cmd(0x29); time.sleep(0.05)                # Display ON

print("Night-Vision Amplified Vector Engine Active...")

screen_w = 240
screen_h = 240

y_block_size = screen_w * screen_h
nv12_frame_size = int(y_block_size * 1.5)
full_frame_buffer = bytearray(screen_w * screen_h * 2)

# --- ADVANCED NVG HIGH-CONTRAST GAMMA LOOKUP MAPS ---
high_byte_map = bytearray(256)
low_byte_map = bytearray(256)

for i in range(256):
    # Boosts dark values non-linearly using a 0.6 gamma power factor
    # to pull hidden textures out of shadows, then scales to 0-255 range
    nvg_boost = int(pow(i / 255.0, 0.6) * 255.0)
    nvg_boost = max(0, min(255, nvg_boost))

    # Map the amplified values straight into standard 16-bit RGB565
    r = nvg_boost >> 3
    g = nvg_boost >> 2
    b = nvg_boost >> 3
    rgb565 = (r << 11) | (g << 5) | b
    high_byte_map[i] = (rgb565 >> 8) & 0xFF
    low_byte_map[i] = rgb565 & 0xFF

trans_high = bytes.maketrans(bytes(range(256)), bytes(high_byte_map))
trans_low  = bytes.maketrans(bytes(range(256)), bytes(low_byte_map))

# Set stream mapping boundaries to match the 240x240 frame block exactly
cmd = [
    "v4l2-ctl", "--device=/dev/video11",
    f"--set-fmt-video=width={screen_w},height={screen_h},pixelformat=NV12",
    "--stream-mmap", "--stream-to=-"
]

try:
    pipe = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=nv12_frame_size)

    while True:
        nv12_data = pipe.stdout.read(nv12_frame_size)
        if len(nv12_data) != nv12_frame_size:
            continue

        y_block = nv12_data[:y_block_size]

        # Translate maps execute at native C speeds
        high_bytes = y_block.translate(trans_high)
        low_bytes  = y_block.translate(trans_low)

        full_frame_buffer[0::2] = high_bytes
        full_frame_buffer[1::2] = low_bytes

        write_cmd(0x2C)
        write_data(full_frame_buffer)

except KeyboardInterrupt:
    print("Halting Video Stream.")
finally:
    try: pipe.terminate()
    except: pass
    spi.close()
