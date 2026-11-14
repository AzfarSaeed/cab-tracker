# Cabline — OSM + Leaflet GPS cab tracker

A local, Uber-inspired tracking GUI with a moving cab icon, route trail, latitude,
longitude, speed, follow mode, and Delhi–Meerut simulation. This is an independent
student prototype, not an Uber product.

## Start the GUI

Requires Python 3.9 or newer and a modern browser. Simulation requires no Python
package installation. Extract the ZIP, open a terminal inside `cab-tracker`, run:

```sh
python3 server.py
```

On Windows, use `py server.py` if `python3` is unavailable.
Open **http://127.0.0.1:8000**, then click **Start journey**.
Do not open `index.html` directly; the application reads its CSV over HTTP.
If port 8000 is in use: `python3 server.py --port 8001`, then open port 8001.
Stop the server with Ctrl+C.

The map uses OpenStreetMap tiles and Leaflet 1.9.4, bundled under `public/vendor`.
Internet is needed for map tiles; the route, library and simulation are local.
No map API key or paid service is needed for this small prototype.

## Simulation dataset

File: `public/data/delhi-meerut-40kmh.csv`

- Origin: Connaught Place, Delhi; destination: central Meerut. Endpoints are snapped
  by OSRM to the driving road network. This route is not specified as the expressway.
- Road geometry: OSRM route using OpenStreetMap, fetched November 2, 2026.
- Route length: **76.437285 km**, measured along the supplied geometry.
- Constant speed: **40.0 km/h** = **11.111111… metres/second**.
- Duration: **6,879.355668 seconds**, approximately **1 h 54 min 39.36 s**.
- **6,881 rows**, including the start, one-second samples, and the destination.
- The final interval is approximately 0.355668 seconds, preserving constant speed
  while reaching the exact destination. The final row is the arrival sample at
  40 km/h; there is no stationary sample after arrival.
- Synthetic start time: November 2, 2026 at **09:00 IST**, saved as **03:30 UTC**.
- Synthetic test data, not a recorded cab trip or a traffic prediction. It intentionally
  omits acceleration, stops, traffic and speed limits as requested.

CSV columns:

| Column | Meaning |
| --- | --- |
| timestamp | ISO 8601 UTC sample time, rounded to milliseconds |
| latitude / longitude | WGS84 decimal degrees |
| speedKph | Always 40.0 |
| heading | Direction of travel, degrees clockwise from true north |
| elapsedSeconds | Time since simulation start, to six decimal places |
| distanceMeters | Cumulative distance along the road geometry |

The generator walks the road geometry at 40 km/h; it does not assign arbitrary
speeds to equally spaced route vertices. Distance is calculated using Haversine
segments with Earth radius 6,371,008.8 metres. At corners, straight-line distances
between sampled coordinates can be slightly shorter than distance along the road.
Use `distanceMeters` / `elapsedSeconds` to verify the constant route speed.

The GUI reads the CSV and interpolates its distance/time over the supplied route
geometry for smooth animation around corners. The default **30× demo playback**
finishes in about 3 min 49 s. Choose **1×** for actual real-time playback. Displayed
vehicle speed remains 40 km/h at every playback rate. Pausing freezes the last sample.

Regenerate the identical CSV offline:

```sh
python3 generate_dataset.py
```

Metadata and attribution are in `public/data/metadata.json`. To import a different
saved OSRM route response, use `python3 generate_dataset.py --osrm-response route.json`.
If changing cities, also update the fixed Delhi/Meerut labels and metadata in the code.

## Connect a real GPS sensor

The sensor must provide a serial/USB data connection, or another program must send
its readings to the local HTTP endpoint. Latitude and longitude do not automatically
arrive in a browser merely because the receiver has power. A UART GPS module usually
needs a suitable USB-to-UART adapter and the module's correct electrical interface.

Install the optional serial dependency (recommended in a virtual environment):

```sh
python3 -m venv .venv
```

Activate it with `source .venv/bin/activate` on macOS/Linux, or
`.venv\Scripts\activate` on Windows, then run:

```sh
python -m pip install -r requirements.txt
python server.py
```

1. Plug in the receiver and open the **Live GPS** tab.
2. Refresh the port list, select the receiver, and select its configured baud rate.
   The default is 9600; your receiver may use 4800, 38400, 115200, etc.
3. Click **Connect GPS**. Give the receiver a clear view of the sky for a valid fix.
4. The first valid reading places the cab at the sensor's actual location. Each new
   reading moves it and updates its coordinates and speed.
5. Click **Disconnect GPS** before unplugging it. Switching to Simulation changes
   the display only; use Disconnect to close an open serial connection.

Examples of device names: `COM3` on Windows, `/dev/ttyUSB0` on Linux, or
`/dev/cu.usbserial-…` on macOS. Port names depend on your hardware. Other applications
must not hold the port open. Use **only one GPS input source at a time**.

Accepted newline-delimited serial formats:

```text
28.632800,77.216700,40.0
```

```json
{"latitude":28.6328,"longitude":77.2167,"speedKph":40,"heading":65}
```

Both formats can omit speed. JSON may include a timezone-qualified `timestamp`;
otherwise receipt time is used. Binary vendor formats require a custom parser.

NMEA `$GPRMC`, `$GNRMC`, `$GPGGA`, `$GNGGA`, and other talker IDs are accepted with
valid checksums. NMEA coordinates are converted from degrees/minutes to decimal
degrees. RMC speed is converted from knots to km/h using **1 knot = 1.852 km/h**.
GGA has no speed; the GUI estimates it from consecutive positions and timestamps
when possible and labels it **ESTIMATED FROM GPS**. GPS jitter can affect that estimate.
Invalid satellite fixes do not move the marker. Missing updates become stale after
10 seconds. The last position remains visible. Duplicate/older timestamps are ignored.

## Feed GPS data from your own program

The local server accepts `POST /api/gps` with `Content-Type: application/json`.
The frontend subscribes to `/api/events` using Server-Sent Events (SSE), which
automatically reconnects. SSE serves the same one-way live-update purpose as
WebSocket in this application while requiring no extra server package.

```python
import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen

reading = {
    "latitude": 28.6328,
    "longitude": 77.2167,
    "speedKph": 40.0,
    "timestamp": datetime.now(timezone.utc).isoformat(),
}
request = Request(
    "http://127.0.0.1:8000/api/gps",
    data=json.dumps(reading).encode(),
    headers={"Content-Type": "application/json"},
)
with urlopen(request) as response:
    print(response.read().decode())
```

If your sensor provides only latitude/longitude, omit `speedKph`. Send one JSON
object per update, with a new timestamp. Report a lost satellite fix with
`{"valid": false}`. Live readings are held in memory; this prototype does not save
a history. The visible live trail is limited to the latest 10,000 samples. Long
signal gaps break the trail rather than counting the gap as travelled distance.

To test the complete HTTP → SSE → live-map path without hardware, open **Live GPS**
and run in a second terminal:

```sh
python3 replay_to_gps.py --rate 30
```

This sends the bundled CSV through the same API used by a real receiver. `--rate 1`
sends approximately one update per second. The script stamps packets with their
transmission time and preserves the explicit CSV speed of 40 km/h. At accelerated
rates, do not infer physical speed from transmission time.

The server binds to **127.0.0.1 only**, for use on the same computer. An ESP32,
cellular GPS device, or remote computer requires an appropriately secured gateway;
this package is not configured as a public telemetry server.

## Files

```text
cab-tracker/
  server.py                 Local web server, HTTP input, SSE output, serial connection
  gps.py                    GPS parsing and validation
  generate_dataset.py       Reproducible constant-speed CSV generator
  replay_to_gps.py           Feed CSV through the live GPS API
  requirements.txt          Optional pySerial dependency
  test_tracker.py           Dataset, parsing, API, streaming and virtual serial tests
  README.md                 Setup and integration guide
  public/
    index.html              GUI layout
    styles.css              Responsive, Uber-inspired design
    app.js                  Leaflet map, CSV playback, live tracking
    data/
      delhi-meerut-40kmh.csv Testing dataset
      route.geojson         Cached road geometry [longitude, latitude]
      metadata.json         Provenance and journey statistics
    vendor/
      leaflet.js
      leaflet.css
      LICENSE-Leaflet.txt
```

Run verification with `python3 -m unittest -v test_tracker.py`. The virtual serial
test uses a pseudo-terminal on macOS/Linux and is skipped if pySerial is missing
or on Windows. It does not require or connect to real hardware.

## Map sources and limitations

- [Leaflet documentation](https://leafletjs.com/reference.html): Leaflet coordinates
  use `[latitude, longitude]`; GeoJSON and OSRM use `[longitude, latitude]`.
- [OSRM API](https://project-osrm.org/docs/v5.24.0/api/): route geometry is cached;
  no routing requests are made during playback.
- [OpenStreetMap tile policy](https://operations.osmfoundation.org/policies/tiles/):
  preserve attribution and browser caching; do not bulk-download map tiles. For
  larger deployments, choose a suitable provider or host your own tiles.
- [OpenStreetMap copyright](https://www.openstreetmap.org/copyright): route/map data
  attribution is retained. The OSRM route is based on OSM data under ODbL.
- [pySerial documentation](https://pyserial.readthedocs.io/en/latest/shortintro.html).

The map's standard OSM street style differs from Uber's proprietary basemap.
The interface borrows the map-first layout, restrained colors and vehicle tracking
interaction. There is no dispatch, booking, fare estimation or turn-by-turn navigation.
Live readings stay on this computer, but OSM receives tile requests for the viewed
area and can infer that map area. Leaflet is bundled locally; no CDN is needed at runtime.
# cab-tracker
