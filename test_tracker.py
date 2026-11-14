import csv
import json
import math
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
import gps
import server
from generate_dataset import distance

DATA=Path(__file__).parent/'public/data'


class DatasetTests(unittest.TestCase):
    def test_constant_speed_timing_and_endpoints(self):
        with (DATA/'delhi-meerut-40kmh.csv').open() as file:
            rows=list(csv.DictReader(file))
        meta=json.loads((DATA/'metadata.json').read_text())
        route=json.loads((DATA/'route.geojson').read_text())['geometry']['coordinates']
        self.assertEqual(len(rows),meta['rows'])
        self.assertGreater(len(rows),6000)
        for row in rows:
            self.assertEqual(float(row['speedKph']),40)
            self.assertTrue(28<float(row['latitude'])<30)
            self.assertTrue(77<float(row['longitude'])<79)
        for a,b in zip(rows,rows[1:]):
            dt=float(b['elapsedSeconds'])-float(a['elapsedSeconds'])
            ds=float(b['distanceMeters'])-float(a['distanceMeters'])
            self.assertGreater(dt,0)
            self.assertLessEqual(dt,1.000001)
            self.assertAlmostEqual(ds/dt*3.6,40,places=4)
        for row,point in ((rows[0],route[0]),(rows[-1],route[-1])):
            self.assertLess(distance([float(row['longitude']),float(row['latitude'])],point),.01)
        length=sum(distance(a,b) for a,b in zip(route,route[1:]))
        self.assertAlmostEqual(length,float(rows[-1]['distanceMeters']),places=5)
        timestamps=[datetime.fromisoformat(r['timestamp'].replace('Z','+00:00')) for r in rows]
        self.assertTrue(all(a<b for a,b in zip(timestamps,timestamps[1:])))
        self.assertAlmostEqual((timestamps[-1]-timestamps[0]).total_seconds(),meta['durationSeconds'],places=2)


class ParserTests(unittest.TestCase):
    def test_rmc_units_and_position(self):
        fix=gps.parse_line('$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A')
        self.assertAlmostEqual(fix['latitude'],48.1173)
        self.assertAlmostEqual(fix['longitude'],11.5166666667)
        self.assertAlmostEqual(fix['speedKph'],41.4848)

    def test_gga_and_unknown_speed(self):
        fix=gps.parse_line('$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47')
        self.assertTrue(fix['valid'])
        self.assertIsNone(fix['speedKph'])

    def test_json_csv_and_invalid_input(self):
        self.assertEqual(gps.parse_line('28.6,77.2,40')['speedKph'],40)
        self.assertIsNone(gps.parse_line('28.6,77.2')['speedKph'])
        self.assertFalse(gps.parse_line('{"valid":false}')['valid'])
        for line in ('91,77,40','28,181,40','28,77,-1','NaN,77,40','$GPRMC,bad*00'):
            with self.assertRaises(ValueError):gps.parse_line(line)
        with self.assertRaises(ValueError):gps.normalize({'latitude':28,'longitude':77,'timestamp':'2026-01-01T00:00:00'})


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.url=f'http://127.0.0.1:{cls.http.server_port}'
        cls.worker=threading.Thread(target=cls.http.serve_forever,daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close()

    def setUp(self):
        server.last_fix=None

    def post(self,payload,origin=None):
        headers={'Content-Type':'application/json'}
        if origin:headers['Origin']=origin
        with urlopen(Request(self.url+'/api/gps',data=json.dumps(payload).encode(),headers=headers),timeout=3) as r:
            return json.load(r)

    def test_http_to_event_stream_and_duplicates(self):
        stream=urlopen(self.url+'/api/events',timeout=3)
        self.assertEqual(stream.readline().strip(),b': connected')
        self.assertEqual(stream.readline().strip(),b'')
        payload={'latitude':28.6328,'longitude':77.2167,'speedKph':40,'timestamp':'2026-11-02T03:30:00Z'}
        self.assertTrue(self.post(payload)['accepted'])
        event=json.loads(stream.readline().decode()[6:])
        self.assertEqual(event['latitude'],28.6328)
        self.assertEqual(event['speedKph'],40)
        self.assertIn('receivedAt',event)
        self.assertFalse(self.post(payload)['accepted'])
        stream.close()

    def test_validation_origin_and_assets(self):
        with self.assertRaises(HTTPError) as e:self.post({'latitude':400,'longitude':77})
        self.assertEqual(e.exception.code,400)
        with self.assertRaises(HTTPError) as e:self.post({'latitude':28,'longitude':77},'https://example.org')
        self.assertEqual(e.exception.code,403)
        for path in ('/','/app.js','/styles.css','/vendor/leaflet.js','/data/delhi-meerut-40kmh.csv'):
            with urlopen(self.url+path,timeout=3) as response:
                self.assertEqual(response.status,200)
                self.assertTrue(response.read())

    def test_same_timestamp_rmc_enriches_gga_speed(self):
        fix={'latitude':28.6,'longitude':77.2,'timestamp':'2026-11-02T03:30:00Z'}
        self.assertTrue(self.post(fix)['accepted'])
        self.assertTrue(self.post(dict(fix,speedKph=40))['accepted'])
        self.assertEqual(server.last_fix['speedKph'],40)
        self.assertFalse(self.post(dict(fix,speedKph=40))['accepted'])

    @unittest.skipUnless(__import__('os').name=='posix','Virtual serial test requires POSIX')
    def test_virtual_serial_input(self):
        try:import serial
        except ImportError:self.skipTest('Install requirements.txt to test serial support')
        import os
        master,slave=os.openpty()
        port=os.ttyname(slave)
        try:
            with patch.object(server,'ports',return_value={'ports':[{'device':port}]}):
                server.connect(port,9600)
                os.write(master,b'28.6328,77.2167,40\n')
                deadline=time.monotonic()+3
                while server.last_fix is None and time.monotonic()<deadline:time.sleep(.03)
                self.assertIsNotNone(server.last_fix)
                self.assertEqual(server.last_fix['speedKph'],40)
                self.assertEqual(server.last_fix['latitude'],28.6328)
        finally:
            server.disconnect();os.close(master);os.close(slave)


if __name__=='__main__':unittest.main()
