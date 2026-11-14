"""Local tracker server: static UI, serial GPS ingestion, HTTP input and SSE output."""
import argparse
import json
import queue
import threading
import time
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from gps import normalize, parse_line

ROOT = Path(__file__).resolve().parent
subscribers = set()
lock = threading.Lock()
last_fix = None
serial_device = None
serial_thread = None
serial_stop = threading.Event()
serial_control = threading.Lock()
serial_state = {'connected': False, 'message': 'GPS not connected', 'port': None}


def publish(fix):
    global last_fix
    with lock:
        if fix.get('valid') and last_fix and last_fix.get('valid'):
            new = datetime.fromisoformat(fix['timestamp'])
            old = datetime.fromisoformat(last_fix['timestamp'])
            enriching = (new == old and fix.get('speedKph') is not None and last_fix.get('speedKph') is None
                         and fix['latitude'] == last_fix['latitude'] and fix['longitude'] == last_fix['longitude'])
            if new < old or (new == old and not enriching):
                return False  # Ignore duplicate/out-of-order packets.
        fix['receivedAt'] = datetime.now(timezone.utc).isoformat()
        last_fix = fix
        for channel in list(subscribers):
            try:
                channel.put_nowait(fix)
            except queue.Full:
                try:
                    channel.get_nowait()
                    channel.put_nowait(fix)
                except (queue.Empty, queue.Full):
                    pass
    return True


def ports():
    try:
        from serial.tools import list_ports
        return {'available': True, 'ports': [{'device': p.device, 'description': p.description} for p in list_ports.comports()]}
    except ImportError:
        return {'available': False, 'ports': [], 'message': 'Install GPS support: python3 -m pip install -r requirements.txt'}


def disconnect():
    global serial_device, serial_thread
    serial_stop.set()
    if serial_thread:
        serial_thread.join(timeout=2)
    if serial_device:
        serial_device.close()
    serial_device = serial_thread = None
    serial_state.update(connected=False, message='GPS disconnected', port=None)


def connect(port, baud):
    global serial_device, serial_thread, last_fix
    import serial
    if port not in [p['device'] for p in ports()['ports']]:
        raise ValueError('Select an available serial port')
    if baud not in (4800, 9600, 19200, 38400, 57600, 115200):
        raise ValueError('Unsupported baud rate')
    disconnect()
    serial_device = serial.Serial(port, baud, timeout=0.5)
    serial_stop.clear()
    with lock:
        last_fix = None
    serial_state.update(connected=True, message='Connected; waiting for a GPS fix', port=port)

    def reader():
        buffer = b''
        try:
            while not serial_stop.is_set():
                buffer += serial_device.read(1024)
                if len(buffer) > 65536:
                    buffer = b''
                    serial_state['message'] = 'Input too long; expected newline-delimited readings'
                while b'\n' in buffer:
                    raw, buffer = buffer.split(b'\n', 1)
                    try:
                        fix = parse_line(raw.decode('ascii').strip())
                        if fix:
                            publish(fix)
                            serial_state['message'] = 'Receiving GPS' if fix['valid'] else 'Connected; no satellite fix'
                    except (ValueError, KeyError, IndexError, TypeError, UnicodeError) as error:
                        serial_state['message'] = f'Ignored invalid reading: {error}'
        except Exception as error:
            serial_state.update(connected=False, message=f'Serial connection lost: {error}')
        finally:
            if serial_device:
                serial_device.close()
            serial_state['connected'] = False
    serial_thread = threading.Thread(target=reader, daemon=True)
    serial_thread.start()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT/'public'), **kwargs)

    def trusted(self):
        host = self.headers.get('Host', '')
        allowed = {f'localhost:{self.server.server_port}', f'127.0.0.1:{self.server.server_port}'}
        origin = self.headers.get('Origin')
        return host in allowed and (not origin or origin in {f'http://{h}' for h in allowed})

    def reply(self, body, status=200):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self.trusted():
            return self.reply({'error':'Use the localhost address printed by the server'},403)
        path = urlparse(self.path).path
        if path == '/api/ports':
            return self.reply(ports())
        if path == '/api/status':
            return self.reply(serial_state)
        if path == '/api/events':
            channel = queue.Queue(maxsize=100)
            with lock:
                subscribers.add(channel)
                if last_fix:
                    channel.put(last_fix)
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.send_header('Cache-Control','no-cache')
            self.end_headers()
            try:
                self.wfile.write(b': connected\n\n')
                self.wfile.flush()
                while True:
                    try:
                        fix = channel.get(timeout=5)
                        packet = 'data: '+json.dumps(fix)+'\n\n'
                    except queue.Empty:
                        packet = ': heartbeat\n\n'
                    self.wfile.write(packet.encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with lock:
                    subscribers.discard(channel)
            return
        try:
            super().do_GET()
        except (BrokenPipeError, ConnectionResetError):
            pass  # Browser navigated away during a static download.

    def do_POST(self):
        if not self.trusted():
            return self.reply({'error':'Cross-origin requests are not allowed'},403)
        try:
            size = int(self.headers.get('Content-Length','0'))
            if size <= 0 or size > 8192:
                raise ValueError('Body must be 1–8192 bytes')
            if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                raise ValueError('Use Content-Type: application/json')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data,dict):
                raise ValueError('Expected a JSON object')
            if self.path == '/api/gps':
                return self.reply({'accepted':publish(normalize(data))})
            if self.path == '/api/serial/connect':
                with serial_control:
                    connect(data['port'],int(data.get('baud',9600)))
                return self.reply(serial_state)
            if self.path == '/api/serial/disconnect':
                with serial_control:
                    disconnect()
                return self.reply(serial_state)
            return self.reply({'error':'Unknown endpoint'},404)
        except (ValueError, KeyError, TypeError, ImportError, OSError) as error:
            return self.reply({'error':str(error)},400)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Cab tracker ready: http://127.0.0.1:{args.port}',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        disconnect()
        server.server_close()
