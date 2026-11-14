"""Optional: replay the supplied CSV through the real GPS HTTP/SSE pipeline."""
import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8000/api/gps')
    parser.add_argument('--rate', type=float, default=1, help='Playback acceleration (speedKph remains 40)')
    args = parser.parse_args()
    if not 0 < args.rate <= 120:
        parser.error('--rate must be greater than 0 and no more than 120')
    with (Path(__file__).parent/'public/data/delhi-meerut-40kmh.csv').open() as file:
        rows=list(csv.DictReader(file))
    started=time.monotonic()
    for i,row in enumerate(rows):
        due=started+float(row['elapsedSeconds'])/args.rate
        time.sleep(max(0,due-time.monotonic()))
        payload={key:float(row[key]) for key in ('latitude','longitude','speedKph','heading')}
        # Timestamp this test packet at transmission; original trip time stays in CSV.
        payload['timestamp']=datetime.now(timezone.utc).isoformat()
        request=Request(args.url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=5) as response:
            result=json.load(response)
        if not result.get('accepted'):
            raise RuntimeError('Server rejected a duplicate/out-of-order reading')
        if i%100==0:
            print(f'{i+1}/{len(rows)} readings sent',flush=True)
    print('Replay complete. The Live GPS view will mark this feed stale after 10 seconds.')


if __name__=='__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nReplay stopped.')
