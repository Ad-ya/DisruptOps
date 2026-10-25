import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIXTURE = Path(__file__).with_name('supplier_fixture.json')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        request = urlparse(self.path)
        data = json.loads(FIXTURE.read_text())
        if request.path.startswith('/shipments/'):
            shipment_id = request.path.rsplit('/', 1)[-1]
            rows = [r for r in data['shipments'] if r['shipment_id'] == shipment_id]
        elif request.path == '/offers':
            material_id = parse_qs(request.query).get('material_id', [''])[0]
            rows = [r for r in data['offers'] if r['material_id'] == material_id]
        else:
            self.send_error(404)
            return
        body = json.dumps({'synthetic': True, 'records': rows}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Synthetic supplier API: http://127.0.0.1:{args.port}', flush=True)
    server.serve_forever()
