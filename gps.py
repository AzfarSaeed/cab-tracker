"""Sensor parsing and common validation; independent of serial-port hardware."""
import json
import math
from datetime import datetime, timedelta, timezone
from functools import reduce
from operator import xor


def number(value, name, low, high):
    if isinstance(value, bool):
        raise ValueError(f'{name} must be a number')
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be between {low} and {high}')
    return value


def normalize(data):
    now = datetime.now(timezone.utc)
    if data.get('valid') is False:
        return {'valid': False, 'timestamp': now.isoformat(), 'source': 'gps'}
    latitude = number(data['latitude'], 'latitude', -90, 90)
    longitude = number(data['longitude'], 'longitude', -180, 180)
    timestamp = data.get('timestamp') or now.isoformat()
    instant = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    if instant.tzinfo is None:
        raise ValueError('timestamp must contain a timezone (Z or +hh:mm)')
    result = dict(latitude=latitude, longitude=longitude, timestamp=instant.astimezone(timezone.utc).isoformat(), valid=True, source='gps')
    result['speedKph'] = None if data.get('speedKph') is None else number(data['speedKph'], 'speedKph', 0, 1000)
    result['heading'] = None if data.get('heading') is None else number(data['heading'], 'heading', 0, 360)
    return result


def coordinate(raw, hemisphere, latitude):
    if hemisphere not in ('NS' if latitude else 'EW') or len(hemisphere) != 1:
        raise ValueError('Invalid NMEA hemisphere')
    value = float(raw)
    degrees, minutes = divmod(value, 100)
    if value < 0 or minutes >= 60:
        raise ValueError('Invalid NMEA coordinate')
    return (degrees + minutes / 60) * (-1 if hemisphere in 'SW' else 1)


def parse_line(line):
    """Accept checksum-validated RMC/GGA, JSON lines, or lat,lon[,speedKph]."""
    line = line.strip()
    if not line:
        return None
    if line.startswith('{'):
        return normalize(json.loads(line))
    if not line.startswith('$'):
        parts = line.split(',')
        if len(parts) not in (2, 3):
            raise ValueError('Expected latitude,longitude[,speedKph]')
        return normalize(dict(latitude=parts[0], longitude=parts[1], speedKph=parts[2] if len(parts)==3 else None))
    body, check = line[1:].split('*', 1)
    if len(check) != 2 or reduce(xor, map(ord, body), 0) != int(check, 16):
        raise ValueError('NMEA checksum mismatch')
    p = body.split(',')
    kind = p[0][-3:]  # GP, GN and other talker IDs
    if kind not in ('RMC', 'GGA'):
        return None
    if len(p) < (10 if kind == 'RMC' else 7):
        raise ValueError('Incomplete NMEA sentence')
    if (kind == 'RMC' and p[2] != 'A') or (kind == 'GGA' and int(p[6] or 0) == 0):
        return normalize({'valid': False})
    if kind == 'RMC':
        instant = datetime.strptime(p[9]+p[1].split('.')[0], '%d%m%y%H%M%S').replace(tzinfo=timezone.utc)
        lat, lon = coordinate(p[3],p[4],True), coordinate(p[5],p[6],False)
        speed = float(p[7])*1.852 if p[7] else None
        heading = float(p[8]) if p[8] else None
    else:
        now = datetime.now(timezone.utc)
        clock = datetime.strptime(p[1].split('.')[0], '%H%M%S').time()
        base = datetime.combine(now.date(),clock,tzinfo=timezone.utc)
        instant = min((base+timedelta(days=d) for d in (-1,0,1)), key=lambda t: abs((t-now).total_seconds()))
        lat, lon = coordinate(p[2],p[3],True), coordinate(p[4],p[5],False)
        speed = heading = None
    if '.' in p[1]:
        instant += timedelta(seconds=float('0.'+p[1].split('.')[1]))
    return normalize(dict(latitude=lat, longitude=lon, speedKph=speed, heading=heading, timestamp=instant.isoformat()))
