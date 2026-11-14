"""Generate a reproducible 40 km/h synthetic trace along the included OSM route."""
import csv
import json
import math
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'public' / 'data'
SPEED_KPH = 40.0


def distance(a, b):
    """Haversine metres; points are GeoJSON [longitude, latitude]."""
    lon1, lat1, lon2, lat2 = map(math.radians, [*a, *b])
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371008.8 * 2 * math.atan2(math.sqrt(h), math.sqrt(max(0, 1-h)))


def bearing(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, [*a, *b])
    return (math.degrees(math.atan2(math.sin(lon2-lon1)*math.cos(lat2),
        math.cos(lat1)*math.sin(lat2)-math.sin(lat1)*math.cos(lat2)*math.cos(lon2-lon1)))+360)%360


def generate():
    route = json.loads((DATA / 'route.geojson').read_text())
    coords = route['geometry']['coordinates']
    cumulative = [0.0]
    for a, b in zip(coords, coords[1:]):
        cumulative.append(cumulative[-1]+distance(a, b))
    total = cumulative[-1]
    duration = total / (SPEED_KPH / 3.6)
    times = list(range(math.floor(duration)+1))
    if duration > times[-1]:
        times.append(duration)  # Short final interval reaches the exact destination at 40 km/h.
    start = datetime(2026, 11, 2, 3, 30, tzinfo=timezone.utc)  # 09:00 IST
    with (DATA / 'delhi-meerut-40kmh.csv').open('w', newline='') as file:
        fields = ['timestamp', 'latitude', 'longitude', 'speedKph', 'heading', 'elapsedSeconds', 'distanceMeters']
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for elapsed in times:
            travelled = min(total, elapsed*SPEED_KPH/3.6)
            i = min(len(coords)-2, bisect_right(cumulative, travelled)-1)
            fraction = (travelled-cumulative[i])/(cumulative[i+1]-cumulative[i])
            lon, lat = [a+(b-a)*fraction for a, b in zip(coords[i], coords[i+1])]
            writer.writerow(dict(timestamp=(start+timedelta(seconds=elapsed)).isoformat(timespec='milliseconds').replace('+00:00','Z'),
                latitude=f'{lat:.8f}', longitude=f'{lon:.8f}', speedKph='40.0', heading=f'{bearing(coords[i],coords[i+1]):.2f}',
                elapsedSeconds=f'{elapsed:.6f}', distanceMeters=f'{travelled:.6f}'))
    metadata = dict(title='Delhi to Meerut • constant 40 km/h', origin='Connaught Place, Delhi',
        destination='Central Meerut', synthetic=True, speedKph=SPEED_KPH, sampleIntervalSeconds=1,
        note='Synthetic movement on an OSRM/OSM road route, not a recorded trip. Final interval may be shorter than one second. No traffic or stops.',
        distanceMeters=total, durationSeconds=duration, rows=len(times), startTime=start.isoformat(),
        routeSource='https://router.project-osrm.org/route/v1/driving/77.2167,28.6328;77.7064,28.9845?overview=full&geometries=geojson&steps=false',
        attribution='© OpenStreetMap contributors; routing by OSRM', routeFetchedOn='2026-11-02')
    (DATA / 'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--osrm-response', type=Path, help='Optional saved OSRM JSON response to import')
    args = parser.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    if args.osrm_response:
        response = json.loads(args.osrm_response.read_text())
        if response.get('code') != 'Ok':
            raise ValueError('OSRM did not return a valid route')
        geometry = response['routes'][0]['geometry']
        geometry['coordinates'] = [p for i,p in enumerate(geometry['coordinates']) if i == 0 or p != geometry['coordinates'][i-1]]
        feature = {'type':'Feature','properties':{'source':'OSRM / OpenStreetMap','attribution':'© OpenStreetMap contributors'},'geometry':geometry}
        (DATA/'route.geojson').write_text(json.dumps(feature)+'\n')
    generate()
