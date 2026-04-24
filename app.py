from flask import Flask, jsonify, request
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import os

app = Flask(__name__)

BODS_API_KEY = os.environ.get("BODS_API_KEY", "a5c23bf799679ed22047938bb8fe3b16611a6fda")

STOP_COORDS = {
    "149000006217": (-0.0978, 50.84094),
    "149000006225": (-0.0978, 50.84094),
}

def get_bods_departures(atcocode):
    coords = STOP_COORDS.get(atcocode, (-0.0978, 50.84094))
    lon, lat = coords
    margin = 0.02
    bbox = f"{lon-margin},{lat-margin},{lon+margin},{lat+margin}"

    url = (f"https://data.bus-data.dft.gov.uk/api/v1/datafeed/"
           f"?api_key={BODS_API_KEY}&boundingBox={bbox}")

    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return []
    except Exception as e:
        print(f"BODS request failed: {e}")
        return []

    ns = {
        's': 'http://www.siri.org.uk/siri'
    }

    try:
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"XML parse failed: {e}")
        return []

    now = datetime.utcnow()
    departures = []

    for activity in root.findall('.//s:VehicleActivity', ns):
        journey = activity.find('s:MonitoredVehicleJourney', ns)
        if journey is None:
            continue

        monitored_call = journey.find('s:MonitoredCall', ns)
        if monitored_call is None:
            continue

        stop_ref = monitored_call.findtext('s:StopPointRef', namespaces=ns)
        if stop_ref != atcocode:
            continue

        line = journey.findtext('s:PublishedLineName', namespaces=ns) or \
               journey.findtext('s:LineRef', namespaces=ns) or '?'

        direction = journey.findtext('s:DestinationName', namespaces=ns) or \
                    journey.findtext('s:DirectionRef', namespaces=ns) or ''

        aimed = monitored_call.findtext('s:AimedArrivalTime', namespaces=ns) or \
                monitored_call.findtext('s:AimedDepartureTime', namespaces=ns)
        expected = monitored_call.findtext('s:ExpectedArrivalTime', namespaces=ns) or \
                   monitored_call.findtext('s:ExpectedDepartureTime', namespaces=ns)

        best_time_str = expected or aimed
        is_live = expected is not None

        if not best_time_str:
            continue

        try:
            # parse ISO time — strip timezone
            t = best_time_str[:19]
            bus_dt = datetime.strptime(t, "%Y-%m-%dT%H:%M:%S")
            mins_away = int((bus_dt - now).total_seconds() / 60)
            best_hhmm = bus_dt.strftime("%H:%M")
        except Exception:
            continue

        if mins_away < -2 or mins_away > 180:
            continue

        departures.append({
            "line": line.strip(),
            "direction": direction.strip(),
            "time": best_hhmm,
            "mins_away": mins_away,
            "live": is_live
        })

    departures.sort(key=lambda x: x["mins_away"])
    return departures[:6]


@app.route('/departures')
def departures():
    atco = request.args.get('atco', '149000006217')
    data = get_bods_departures(atco)
    return jsonify({
        "atco": atco,
        "count": len(data),
        "departures": data,
        "fetched_at": datetime.utcnow().strftime("%H:%M")
    })


@app.route('/health')
def health():
    return jsonify({"status": "ok"})

@app.route('/debug')
def debug():
    coords = (-0.0978, 50.84094)
    lon, lat = coords
    margin = 0.02
    bbox = f"{lon-margin},{lat-margin},{lon+margin},{lat+margin}"
    url = (f"https://data.bus-data.dft.gov.uk/api/v1/datafeed/"
           f"?api_key={BODS_API_KEY}&boundingBox={bbox}")
    r = requests.get(url, timeout=15)
    
    ns = {'s': 'http://www.siri.org.uk/siri'}
    root = ET.fromstring(r.content)
    
    activities = root.findall('.//s:VehicleActivity', ns)
    if not activities:
        return jsonify({"error": "no vehicles"})
    
    # return raw XML of first vehicle so we can see all fields
    import xml.etree.ElementTree as ET2
    raw = ET2.tostring(activities[0], encoding='unicode')
    
    return app.response_class(raw, mimetype='text/xml')
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
