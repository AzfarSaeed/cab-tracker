'use strict';
const $ = id => document.getElementById(id);
const notice = message => { $('notice').textContent = message; $('notice').hidden = !message; };
if (!window.L) {
  notice('The map library could not load. Check that the vendor folder is present, then reload.');
  throw new Error('Leaflet unavailable');
}
const map = L.map('map', {zoomControl:false}).setView([28.8,77.46],10);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom:19, attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).on('tileerror', () => notice('Map tiles could not load. Check your internet connection. Tracking and CSV playback still work.')).addTo(map);
const routeLayer = L.polyline([], {color:'#adb5a9',weight:5,opacity:.85}).addTo(map);
const trailLayer = L.polyline([], {color:'#17261d',weight:5,opacity:1}).addTo(map);
const endpoints = L.layerGroup().addTo(map);
const carSvg = '<div class="car-rotate"><svg viewBox="0 0 32 52" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="10" width="5" height="9" rx="2" fill="#181d1a"/><rect x="25" y="10" width="5" height="9" rx="2" fill="#181d1a"/><rect x="2" y="35" width="5" height="9" rx="2" fill="#181d1a"/><rect x="25" y="35" width="5" height="9" rx="2" fill="#181d1a"/><rect x="5" y="2" width="22" height="48" rx="8" fill="#fdfefd" stroke="#78847a" stroke-width="1.5"/><path d="M8 14L24 14L22 22L10 22Z" fill="#263a30"/><rect x="10" y="24" width="12" height="12" rx="2" fill="#e2e8df"/><path d="M10 38L22 38L24 43L8 43Z" fill="#334b3d"/><path d="M8 7h4m8 0h4" stroke="#ecdb94" stroke-width="3"/><path d="M8 46h4m8 0h4" stroke="#b45b4f" stroke-width="2"/></svg></div>';
const marker = L.marker([28.6328,77.2167],{icon:L.divIcon({className:'car-icon',html:carSvg,iconSize:[32,52],iconAnchor:[16,26]}),zIndexOffset:1000});
let mode='simulation', rows=[], geometry=[], cumulative=[], duration=0, elapsed=0, playing=false, follow=false;
let meta=null, stream=null, liveFix=null, liveTrail=[], liveDistance=0, latestReceived=0, liveValid=false, sensorClock=0;
let liveAnimation=null, lastFrame=performance.now(), lastPan=0, lastPoll=0, explicitlyDisconnected=false;
const meters=(a,b)=>map.distance(a,b);
const clock=seconds=>{const s=Math.floor(seconds);return `${Math.floor(s/3600)?String(Math.floor(s/3600)).padStart(2,'0')+':':''}${String(Math.floor(s/60)%60).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;};
function status(text,active=false){$('status').textContent=text;$('statusDot').classList.toggle('active',active);}
function setFollow(value){follow=value;$('follow').setAttribute('aria-pressed',String(value));if(value&&map.hasLayer(marker))map.setView(marker.getLatLng(),Math.max(map.getZoom(),14));}
function showPoint(lat,lon,heading){
  if(!map.hasLayer(marker))marker.addTo(map);
  marker.setLatLng([lat,lon]);
  const icon=marker.getElement()?.querySelector('.car-rotate');
  if(icon&&Number.isFinite(heading))icon.style.transform=`rotate(${heading}deg)`;
  if(follow&&performance.now()-lastPan>650){map.panTo([lat,lon],{animate:true,duration:.5});lastPan=performance.now();}
}
function readings(fix){
  $('latitude').textContent=fix.latitude.toFixed(6);
  $('longitude').textContent=fix.longitude.toFixed(6);
  $('speed').textContent=Number.isFinite(fix.speedKph)?fix.speedKph.toFixed(fix.speedKph%1?1:0):'—';
}
function segmentAt(list,value){let lo=0,hi=list.length-1;while(lo<hi){const mid=Math.ceil((lo+hi)/2);if(list[mid]<=value)lo=mid;else hi=mid-1;}return Math.min(lo,list.length-2);}
function routePoint(distance){
  const i=segmentAt(cumulative,distance),a=geometry[i],b=geometry[i+1];
  const t=Math.min(1,Math.max(0,(distance-cumulative[i])/(cumulative[i+1]-cumulative[i])));
  return {point:[a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t],index:i};
}
function renderSimulation(){
  if(!rows.length)return;
  const i=Math.min(Math.floor(elapsed),rows.length-2),a=rows[i],b=rows[i+1];
  const t=Math.min(1,Math.max(0,(elapsed-a.elapsedSeconds)/(b.elapsedSeconds-a.elapsedSeconds)));
  const distance=a.distanceMeters+(b.distanceMeters-a.distanceMeters)*t;
  const position=routePoint(distance);
  const fix={latitude:position.point[0],longitude:position.point[1],speedKph:a.speedKph};
  showPoint(fix.latitude,fix.longitude,a.heading);readings(fix);
  // Include every road vertex so the travelled trail follows corners.
  trailLayer.setLatLngs([...geometry.slice(0,position.index+1),position.point]);
  $('seek').value=duration?elapsed/duration*1000:0;
  $('elapsed').textContent=clock(elapsed);$('progressText').textContent=`${Math.floor(elapsed/duration*100)}%`;
  $('distanceTravelled').textContent=`${(distance/1000).toFixed(2)} km travelled`;
  $('lastUpdate').textContent=new Date(Date.parse(rows[0].timestamp)+elapsed*1000).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',second:'2-digit'})+' IST';
  $('speedLabel').textContent=playing?'VEHICLE SPEED':'LAST SAMPLE SPEED';
  $('vehicleState').textContent=elapsed>=duration?'ARRIVED':playing?'MOVING':elapsed?'PAUSED':'READY';
  status(elapsed>=duration?'Journey complete':playing?'Cab moving · 40 km/h':elapsed?'Simulation paused':'Ready for the road',playing);
  $('play').textContent=playing?'Ⅱ Pause journey':elapsed>=duration?'↺ Replay journey':'▶ Start journey';
}
function fit(){
  setFollow(false);
  const points=mode==='simulation'?geometry:liveTrail;
  if(points.length>1)map.fitBounds(L.latLngBounds(points),{paddingTopLeft:[45,90],paddingBottomRight:[60,250],maxZoom:15});
  else if(points.length)map.setView(points[0],15);
}
async function getJSON(url,options){const response=await fetch(url,options);const body=await response.json();if(!response.ok)throw new Error(body.error||`Request failed (${response.status})`);return body;}
const post=(url,data)=>getJSON(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
async function refreshPorts(){
  try{const result=await getJSON('/api/ports');$('port').replaceChildren(new Option(result.ports.length?'Select a device':'No serial ports found',''));
    result.ports.forEach(p=>$('port').add(new Option(`${p.device} · ${p.description}`,p.device)));
    $('serialStatus').textContent=result.available?(result.ports.length?'Choose your receiver and its configured baud rate.':'No serial device detected. Connect the GPS, then refresh.'):result.message;
  }catch(error){$('serialStatus').textContent=error.message;}
}
function acceptGPS(fix){
  if(mode!=='live')return;
  latestReceived=Date.parse(fix.receivedAt)||Date.now();
  liveValid=fix.valid!==false;
  if(!liveValid){$('speed').textContent='—';status('No satellite fix');$('vehicleState').textContent='NO FIX';return;}
  if(!Number.isFinite(fix.latitude)||!Number.isFinite(fix.longitude))return;
  const timestamp=Date.parse(fix.timestamp);
  if(!Number.isFinite(timestamp)||timestamp<sensorClock)return;
  explicitlyDisconnected=false;
  if(timestamp===sensorClock){
    if(liveFix&&fix.speedKph!=null){liveFix=fix;readings(fix);$('speedLabel').textContent='GPS SPEED';}
    return;
  }
  sensorClock=timestamp;
  const point=[fix.latitude,fix.longitude];
  let estimated=false;
  if(liveFix){
    const distance=meters([liveFix.latitude,liveFix.longitude],point),dt=(timestamp-Date.parse(liveFix.timestamp))/1000;
    // Do not join a long signal gap with a misleading travelled line.
    if(dt>0&&dt<=10){liveDistance+=distance;if(fix.speedKph==null){fix.speedKph=distance/dt*3.6;estimated=true;}}
    else liveTrail=[];
  }
  const first=!liveFix;
  liveAnimation={from:map.hasLayer(marker)?marker.getLatLng():L.latLng(point),to:L.latLng(point),start:performance.now(),heading:fix.heading};
  liveFix=fix;liveTrail.push(point);if(liveTrail.length>10000)liveTrail.shift();
  trailLayer.setLatLngs(liveTrail);readings(fix);
  $('speedLabel').textContent=estimated?'ESTIMATED FROM GPS':'GPS SPEED';
  $('distanceTravelled').textContent=`${(liveDistance/1000).toFixed(2)} km observed`;
  if(first){showPoint(...point,fix.heading);map.setView(point,15);setFollow(true);}
  updateLiveStatus();
}
function updateLiveStatus(){
  if(explicitlyDisconnected){status('GPS disconnected');$('vehicleState').textContent='OFFLINE';return;}
  if(!latestReceived){status('Waiting for GPS data');$('vehicleState').textContent='WAITING';return;}
  const age=Math.max(0,(Date.now()-latestReceived)/1000);
  $('lastUpdate').textContent=`Received ${Math.floor(age)}s ago`;
  if(!liveValid){status('No satellite fix');$('vehicleState').textContent='NO FIX';}
  else if(age>10){status('GPS signal stale');$('vehicleState').textContent='STALE';$('speedLabel').textContent='LAST KNOWN SPEED';}
  else{status('Receiving live GPS',true);$('vehicleState').textContent='LIVE';}
}
function switchMode(next){
  if(mode===next)return;
  mode=next;playing=false;liveAnimation=null;
  $('simulationTab').classList.toggle('selected',mode==='simulation');$('liveTab').classList.toggle('selected',mode==='live');
  $('simulationTab').setAttribute('aria-pressed',String(mode==='simulation'));$('liveTab').setAttribute('aria-pressed',String(mode==='live'));
  $('simulationPanel').hidden=mode!=='simulation';$('livePanel').hidden=mode!=='live';$('modeBadge').textContent=mode==='simulation'?'SIMULATION':'LIVE GPS';
  setFollow(false);trailLayer.setLatLngs([]);marker.remove();
  if(stream){stream.close();stream=null;}
  if(mode==='simulation'){
    routeLayer.addTo(map);endpoints.addTo(map);$('vehicleCaption').textContent='Delhi → Meerut';
    $('modeNote').textContent='Synthetic test drive · OSM road geometry. No traffic or stops.';
    renderSimulation();fit();
  }else{
    routeLayer.remove();endpoints.remove();liveFix=null;liveTrail=[];liveDistance=0;latestReceived=0;liveValid=false;sensorClock=0;explicitlyDisconnected=false;
    ['speed','latitude','longitude'].forEach(id=>$(id).textContent='—');$('distanceTravelled').textContent='0.00 km observed';$('lastUpdate').textContent='Waiting for a fix';
    $('vehicleCaption').textContent='Your connected GPS receiver';$('modeNote').textContent='Live GPS · readings stay on this computer. No fix for 10 seconds is marked stale.';
    updateLiveStatus();refreshPorts();
    stream=new EventSource('/api/events');stream.onmessage=event=>{try{acceptGPS(JSON.parse(event.data));}catch(error){notice('Invalid GPS event: '+error.message);}};
    stream.onerror=()=>status('Reconnecting to local server…');
  }
}
$('simulationTab').onclick=()=>switchMode('simulation');$('liveTab').onclick=()=>switchMode('live');
$('play').onclick=()=>{if(elapsed>=duration)elapsed=0;playing=!playing;lastFrame=performance.now();renderSimulation();};
$('reset').onclick=()=>{elapsed=0;playing=false;renderSimulation();fit();};
$('seek').oninput=()=>{elapsed=Number($('seek').value)/1000*duration;renderSimulation();};
$('fit').onclick=fit;$('follow').onclick=()=>setFollow(!follow);
$('zoomIn').onclick=()=>map.zoomIn();$('zoomOut').onclick=()=>map.zoomOut();map.on('dragstart',()=>setFollow(false));
$('refreshPorts').onclick=refreshPorts;
$('connect').onclick=async()=>{if(!$('port').value){$('serialStatus').textContent='Select a GPS device first.';return;}$('connect').disabled=true;
  try{const result=await post('/api/serial/connect',{port:$('port').value,baud:Number($('baud').value)});sensorClock=0;explicitlyDisconnected=false;$('serialStatus').textContent=result.message;}catch(error){$('serialStatus').textContent=error.message;}finally{$('connect').disabled=false;}};
$('disconnect').onclick=async()=>{try{const result=await post('/api/serial/disconnect',{});$('serialStatus').textContent=result.message;liveValid=false;explicitlyDisconnected=true;updateLiveStatus();}catch(error){$('serialStatus').textContent=error.message;}};
function frame(now){
  if(mode==='simulation'&&playing&&rows.length){elapsed=Math.min(duration,elapsed+(now-lastFrame)/1000*Number($('rate').value));if(elapsed>=duration)playing=false;renderSimulation();}
  if(mode==='live'){
    if(liveAnimation){const t=Math.min(1,(now-liveAnimation.start)/700),a=liveAnimation.from,b=liveAnimation.to;showPoint(a.lat+(b.lat-a.lat)*t,a.lng+(b.lng-a.lng)*t,liveAnimation.heading);if(t>=1)liveAnimation=null;}
    if(now-lastPoll>1000){lastPoll=now;updateLiveStatus();getJSON('/api/status').then(s=>{if(s.connected)$('serialStatus').textContent=s.message;}).catch(()=>{});}
  }
  lastFrame=now;requestAnimationFrame(frame);
}
async function boot(){
  try{
    const [metadata,route,response]=await Promise.all([getJSON('data/metadata.json'),getJSON('data/route.geojson'),fetch('data/delhi-meerut-40kmh.csv')]);
    if(!response.ok)throw new Error('Simulation CSV is missing');
    const lines=(await response.text()).trim().split(/\r?\n/),headers=lines.shift().split(',');
    rows=lines.map(line=>Object.fromEntries(line.split(',').map((value,i)=>[headers[i],headers[i]==='timestamp'?value:Number(value)])));
    if(rows.length<2||rows.some(r=>!Number.isFinite(r.latitude)||!Number.isFinite(r.longitude)||r.speedKph!==40))throw new Error('Invalid simulation dataset');
    meta=metadata;geometry=route.geometry.coordinates.map(([lon,lat])=>[lat,lon]);cumulative=[0];
    for(let i=1;i<geometry.length;i++)cumulative.push(cumulative[i-1]+meters(geometry[i-1],geometry[i]));
    // Leaflet uses radius 6371000m; rescale to the generator's 6371008.8m metric.
    const scale=rows.at(-1).distanceMeters/cumulative.at(-1);cumulative=cumulative.map(d=>d*scale);
    duration=rows.at(-1).elapsedSeconds;routeLayer.setLatLngs(geometry);
    [[geometry[0],'Delhi · start',''],[geometry.at(-1),'Meerut · destination',' destination']].forEach(([point,label,extra])=>L.marker(point,{icon:L.divIcon({className:'endpoint'+extra,iconSize:[16,16],iconAnchor:[8,8]})}).bindTooltip(label,{direction:'top',offset:[0,-8]}).addTo(endpoints));
    $('routeDistance').textContent=`${(meta.distanceMeters/1000).toFixed(1)} km`;
    $('routeDuration').textContent=`${Math.floor(duration/3600)}h ${Math.round(duration%3600/60)}m`;$('totalTime').textContent=clock(duration);
    ['play','reset','seek'].forEach(id=>$(id).disabled=false);
    if(mode==='simulation'){renderSimulation();fit();}else{routeLayer.remove();endpoints.remove();}
  }catch(error){notice('Could not load the simulation: '+error.message);status('Simulation unavailable');}
}
boot();requestAnimationFrame(frame);
