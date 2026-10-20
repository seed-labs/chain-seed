"use strict";
const $ = id => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const colors = {beacon: "#087e82", geth: "#b56b26", validator: "#486baf"};
let data = null, layer = "service", selected = null, focus = false, paused = false, objectType = "block", replay = 1, timer = null;
let lastObject = "", objectGroups = new Map();
let followLatest = true;
const pinned = new Set();
const fmt = (v, digits=2) => v == null ? "Unavailable" : Number(v).toFixed(digits);
const clock = t => t ? new Date(t*1000).toISOString().slice(11,23) + " UTC" : "Unknown time";
const age = t => t ? `${Math.max(0, Math.round(Date.now()/1000-t))}s old` : "not sampled";
function el(tag, attrs={}, text="") { const n=document.createElementNS(NS,tag); for(const [k,v] of Object.entries(attrs)) n.setAttribute(k,v); if(text) n.textContent=text; return n; }
function html(tag, cls, text) {const n=document.createElement(tag); if(cls)n.className=cls; if(text!=null)n.textContent=text;return n;}
function download(name, body, type) {const a=document.createElement("a");const url=URL.createObjectURL(new Blob([body],{type}));a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function metric(node, kind="api_request_p0") {return (node.metrics||[]).find(m=>m.type===kind);}
function nodeColor(node) {
 const key=$("color").value;
 if(key==="role")return colors[node.role]||"#728384";
 const value=key==="memory"?node.memory_gib:key==="queue"?metric(node)?.queue_mean:node.head;
 if(value==null)return "#b9c5c1";
 const all=data.nodes.map(n=>key==="memory"?n.memory_gib:key==="queue"?metric(n)?.queue_mean:n.head).filter(v=>v!=null);
 const low=Math.min(...all),high=Math.max(...all),t=(value-low)/Math.max(high-low,.001);
 return `hsl(${172-t*145} 48% ${43-t*5}%)`;
}
function activeEvents() {return objectType==="block" ? objectGroups.get($("object").value)||[] : [];}
function observedNodes() {
 const events=activeEvents(); if(!events.length)return null;
 const start=Math.min(...events.map(e=>e.at)),end=Math.max(...events.map(e=>e.at));
 return new Set(events.filter(e=>e.at<=start+(end-start)*replay).map(e=>e.node));
}
function chooseNode(id) {selected=id;renderDetail();renderGraph();}
function renderGraph() {
 if(!data)return;
 const svg=$("graph");svg.replaceChildren();
 const asn=$("asn").value,q=$("search").value.trim().toLowerCase();
 const searchingNode=q && !q.startsWith("0x") && !/^\d+$/.test(q);
 const neighborhood=new Set([selected]);if(focus)for(const e of data.edges){if(e.kind===(layer==="service"?"service":"peer")&&(e.source===selected||e.target===selected)){neighborhood.add(e.source);neighborhood.add(e.target);}}
 let nodes=data.nodes.filter(n=>(layer==="service"||n.role===layer)&&($("chain").value==="all"||n.chain===$("chain").value)&&(focus?neighborhood.has(n.id):(asn==="all"||n.asn===asn)));
 if(searchingNode)nodes=nodes.filter(n=>[n.label,n.id,n.ip,`AS${n.asn}`].some(v=>v.toLowerCase().includes(q)));
 const aggregate=asn==="all"&&!searchingNode&&!focus;
 const groups=new Map();
 nodes.forEach(n=>{const key=aggregate?n.asn:n.id;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(n);});
 const list=[...groups.entries()].sort((a,b)=>a[0].localeCompare(b[0],undefined,{numeric:true}));
 const width=Math.max(320,svg.clientWidth||1050);
 const cols=Math.min(8,Math.max(1,Math.floor((width-50)/100)),Math.max(1,Math.ceil(Math.sqrt(list.length*1.65))));
 const rows=Math.ceil(list.length/cols),height=Math.max(360,rows*76+40),positions=new Map();
 svg.setAttribute("viewBox",`0 0 ${width} ${height}`);
 list.forEach(([key],i)=>positions.set(key,{x:45+(i%cols)*((width-90)/Math.max(cols-1,1)),y:45+Math.floor(i/cols)*(Math.min(100,(height-90)/Math.max(rows-1,1)))}));
 if(cols===1)for(const p of positions.values())p.x=width/2;
 const visible=new Set(nodes.map(n=>n.id)),nodeById=new Map(nodes.map(n=>[n.id,n]));
 const edges=data.edges.filter(e=>e.kind===(layer==="service"?"service":"peer")&&visible.has(e.source)&&visible.has(e.target));
 const edgeGroups=new Map();
 edges.forEach(e=>{const a=aggregate?nodeById.get(e.source).asn:e.source,b=aggregate?nodeById.get(e.target).asn:e.target;if(a===b)return;const key=[a,b].sort().join("|");const g=edgeGroups.get(key)||{a,b,count:0};g.count++;edgeGroups.set(key,g);});
 for(const e of edgeGroups.values()) {const a=positions.get(e.a),b=positions.get(e.b);svg.append(el("line",{x1:a.x,y1:a.y,x2:b.x,y2:b.y,stroke:layer==="service"?"#9caeaa":"#a3c6c2","stroke-width":aggregate?Math.min(3,1+Math.log2(e.count)/2):1.1,opacity:aggregate?.32:.55,"stroke-dasharray":layer==="service"?"4 4":"none"}));}
 const observed=observedNodes();
 for(const [key,members] of list) {
  const p=positions.get(key),node=members[0],isSelected=!aggregate&&selected===node.id;
  const group=el("g",{class:"node",tabindex:0,role:"button","aria-label":aggregate?`Expand AS ${key}`:`Select ${node.label}`,transform:`translate(${p.x} ${p.y})`});
  const mean=values=>{const xs=values.filter(v=>v!=null);return xs.length?xs.reduce((a,b)=>a+b,0)/xs.length:null;};
  const aggregateNode={...node,memory_gib:mean(members.map(n=>n.memory_gib)),head:mean(members.map(n=>n.head)),metrics:[{type:"api_request_p0",queue_mean:mean(members.map(n=>metric(n)?.queue_mean))}]};
  const fill=aggregate?($("color").value==="role"?"#fffef9":nodeColor(aggregateNode)):nodeColor(node);
  group.append(el("circle",{r:aggregate?22:12,fill,stroke:isSelected?"#172c35":"#bed3cc","stroke-width":isSelected?3:1.4}));
  if(observed&&members.some(n=>observed.has(n.id)))group.append(el("circle",{r:aggregate?26:16,fill:"none",stroke:"#dc983a","stroke-width":2.5}));
  if(aggregate) {group.append(el("text",{"text-anchor":"middle",y:4,"font-size":12,"font-weight":"bold",style:`fill:${$("color").value==="role"||fill==="#b9c5c1"?"#172c35":"white"}`},String(members.length)));group.append(el("text",{"text-anchor":"middle",y:40,"font-size":11},`AS ${key}`));}
  else {group.append(el("text",{"text-anchor":"middle",y:29,"font-size":10,"font-weight":isSelected?"bold":"normal"},node.label));}
  group.append(el("title",{},aggregate?`AS ${key}: ${members.length} nodes. Click to expand.`:`${node.label} · ${node.ip} · Memory ${fmt(node.memory_gib,3)} GiB`));
  const activate=()=>{if(aggregate){$("asn").value=key;renderGraph();}else chooseNode(node.id);};
  group.addEventListener("click",activate);group.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();activate();}});svg.append(group);
 }
 $("map-title").textContent=layer==="service"?"Client dependency map":`${layer==="beacon"?"Beacon":"Geth"} peer network`;
 $("map-kicker").textContent=focus?"NEIGHBORHOOD · CROSS-AS LINKS":aggregate?"AS GROUPS · SELECT TO EXPAND":"NODE VIEW · SELECT TO INSPECT";
 $("counts").textContent=`${nodes.length} nodes · ${edges.length} ${layer==="service"?"service relations":"reported links"}`;
 $("edge-legend").textContent=layer==="service"?"Dashed line = configured dependency, not P2P":"Line = reported connection, not message path";
 $("coverage").textContent=(layer==="service"?"Configured client dependencies and sampled runtime command flags. Network-layer router paths are not represented.":data.capabilities.peer_graph)+($("color").value!=="role"?" Color: teal = lower, amber = higher; gray = unknown. AS color averages available samples only.":"");
 $("empty").hidden=nodes.length>0;
 $("empty").textContent="No nodes match this selection. Reset filters to return to the network.";
}
function addRow(root,label,value){const row=html("div","detail-row");row.append(html("span","",label),html("span","",value));root.append(row);}
function spark(root,series,key,color){if(series.length<2){root.append(html("p","muted","Trend appears after two resource samples; no synthetic history is backfilled."));return;}const values=series.map(s=>s[key]).filter(v=>v!=null);if(values.length<2)return;const lo=Math.min(...values),hi=Math.max(...values),s=el("svg",{viewBox:"0 0 270 64",class:"spark",role:"img","aria-label":`${key} since attachment`});s.append(el("line",{x1:0,y1:54,x2:270,y2:54,stroke:"#d9e1df"}));s.append(el("polyline",{points:values.map((v,i)=>`${i/(values.length-1)*270},${48-(v-lo)/Math.max(hi-lo,.001)*38}`).join(" "),fill:"none",stroke:color,"stroke-width":2}));root.append(s);}
function renderDetail(){
 const root=$("detail");root.replaceChildren();if(!data)return;
 const node=data.nodes.find(n=>n.id===selected);
 if(!node){root.append(html("span","eyebrow","INSPECTOR"),html("h2","","Every node, in context."),html("p","intro","Open an AS group, then select a node to inspect resources, local processing pressure and its client dependencies."));addRow(root,"Resource data","Existing experiment samples");addRow(root,"Peer links",data.mode==="demo"?"Synthetic fixture":"Optional read-only probe");addRow(root,"Message sender","Not instrumented");root.append(html("p","aside-note","Block highlights show observer arrival order, not forwarding paths. Missing data is unknown, never zero."));return;}
 root.append(html("span","eyebrow","NODE INSPECTOR"),html("h2","",node.label),html("span","detail-tag",`${node.role.toUpperCase()} · AS ${node.asn}`));
 const focusButton=html("button","focus-button",focus?"Exit neighborhood":"Show neighborhood");focusButton.onclick=()=>{focus=!focus;if(focus){layer=node.role==="validator"?"service":node.role;$("search").value="";document.querySelectorAll("[data-layer]").forEach(b=>b.classList.toggle("active",b.dataset.layer===layer));}renderGraph();renderDetail();};root.append(focusButton);
 const pin=html("button","focus-button",pinned.has(node.id)?"Remove comparison":"Pin for comparison (max 4)");pin.disabled=!pinned.has(node.id)&&pinned.size>=4;pin.onclick=()=>{if(pinned.has(node.id))pinned.delete(node.id);else pinned.add(node.id);renderDetail();renderComparison();};root.append(pin);
 const m=html("div","detail-metrics");for(const [label,value] of [["Memory / GiB",fmt(node.memory_gib,3)],["CPU / % of one core",fmt(node.cpu,1)]]){const tile=html("div","metric");tile.append(html("span","",label),html("strong",value==="Unavailable"?"unknown":"",value));m.append(tile);}root.append(m);
 if(node.chain)addRow(root,"Chain",`${node.chain} · ${node.consensus} · ID ${node.chain_id}`);
 addRow(root,"Address",node.ip);addRow(root,"Resource sample",age(node.at));
 if(node.role==="geth"&&node.rpc_port===null)addRow(root,"RPC","Disabled in Server configuration");
 if(node.role==="beacon"&&node.metrics_port===null)addRow(root,"Metrics","Disabled in Server configuration");
 if(node.static_peers?.length)addRow(root,"Configured outbound peers",node.static_peers.join(", "));
 if(node.head!=null)addRow(root,"Observed head slot",fmt(node.head,0));
 if(node.cap)addRow(root,"Worker cap (configuration)",node.cap);
 if(node.keys!=null)addRow(root,"Keys / VC (configuration)",node.keys);
 const p=node.peer_probe;const metrics=node.metrics||[];const peerMetric=metrics.find(m=>m.peers!=null);
 addRow(root,"Peer count",node.role==="validator"?"N/A (uses Beacon API)":p?.error?`Query failed · ${age(p.at)}`:p?.count!=null?`${p.count} · ${age(p.at)}`:peerMetric?`${peerMetric.peers} · ${age(peerMetric.at)}`:"Not sampled");
 if(p?.error)root.append(html("p","aside-note",`Peer probe error: ${p.error}`));
 if(node.txpool){addRow(root,"Local txpool pending",String(node.txpool.pending));addRow(root,"Local txpool queued",String(node.txpool.queued));addRow(root,"Txpool sample",age(node.txpool.at));}
 const queue=metric(node);addRow(root,"API P0 sampled mean",node.role!=="beacon"?"N/A (Beacon only)":queue?`${fmt(queue.queue_mean,3)} · ${age(queue.at)}`:"Not sampled");
 if(node.metrics_error)addRow(root,"Metrics query error",node.metrics_error);
 if(queue)addRow(root,"Workers active",fmt(queue.workers,0));
 if(queue){addRow(root,"Processor sample",age(queue.at));root.append(html("p","aside-note","Queue value is the mean at observed queue events between two scrapes, not instantaneous queue depth or a time-weighted average."));}
 if(metrics.length){const more=html("details","processing-detail");more.append(html("summary","","Other processor queues"));for(const m of metrics.filter(m=>m.type!=="api_request_p0")){addRow(more,m.type,fmt(m.queue_mean,3));}root.append(more);}
 root.append(html("p","small-title","MEMORY · SINCE ATTACHMENT"));spark(root,node.series||[],"memory",colors[node.role]);
 const neighbors=[...new Set(data.edges.filter(e=>e.source===node.id||e.target===node.id).map(e=>e.source===node.id?e.target:e.source))];root.append(html("p","small-title",`RELATED NODES · ${neighbors.length}`));const list=html("div","neighbor-list");neighbors.slice(0,16).forEach(id=>{const n=data.nodes.find(n=>n.id===id);const b=html("button","",n?.label||id);b.onclick=()=>{layer="service";document.querySelectorAll("[data-layer]").forEach(b=>b.classList.toggle("active",b.dataset.layer===layer));$("asn").value=n?.asn||"all";chooseNode(id);};list.append(b);});root.append(list);
 root.append(html("p","aside-note","Peer edges and configured service relations are different evidence types. Inspect the corresponding map layer."));
}
function renderComparison(){const root=$("comparison");root.replaceChildren();root.hidden=pinned.size===0;if(!pinned.size)return;root.append(html("span","eyebrow","MATCHED VIEW · LATEST AVAILABLE SAMPLE"),html("h2","","Node comparison"));const cards=html("div","compare-grid");for(const id of pinned){const n=data.nodes.find(n=>n.id===id);if(!n)continue;const card=html("article","compare-card");const close=html("button","",`${n.label} · remove`);close.onclick=()=>{pinned.delete(id);renderComparison();renderDetail();};card.append(close);addRow(card,"Memory / GiB",fmt(n.memory_gib,3));addRow(card,"CPU / % one core",fmt(n.cpu,1));addRow(card,"API P0 mean",fmt(metric(n)?.queue_mean,3));addRow(card,"Resource age",age(n.at));addRow(card,"Processor age",age(metric(n)?.at));cards.append(card);}root.append(cards,html("p","muted","Samples may have different timestamps. Comparison is descriptive, not a controlled treatment or causal result."));}
function buildObjects(){
 objectGroups=new Map();for(const event of data.events){if(!event.at)continue;const key=event.hash;if(!objectGroups.has(key))objectGroups.set(key,[]);objectGroups.get(key).push(event);}
 const q=$("search").value.trim().toLowerCase(), old=$("object").value;
 let options=objectType==="block"?[...objectGroups.entries()].map(([hash,ev])=>({hash,at:Math.max(...ev.map(e=>e.at)),label:`Slot ${ev[0].slot} · ${hash.slice(0,12)}…`,slot:ev[0].slot})):data.transactions.map(t=>({hash:t.hash,at:t.accepted_at,label:`${t.kind} · ${t.hash.slice(0,14)}…`,slot:""}));
 if(q.startsWith("0x")||/^\d+$/.test(q))options=options.filter(o=>o.hash.toLowerCase().includes(q)||o.slot===q);
 options.sort((a,b)=>(objectType==="block"?Number(b.slot)-Number(a.slot):0)||b.at-a.at);options=options.slice(0,100);$("object").replaceChildren();for(const o of options){const option=document.createElement("option");option.value=o.hash;option.textContent=o.label;$("object").append(option);}if((!followLatest||paused)&&options.some(o=>o.hash===old))$("object").value=old;
 $("follow").textContent=followLatest?"Following latest":"Follow latest";$("follow").setAttribute("aria-pressed",String(followLatest));
 $("play").disabled=objectType!=="block"||!options.length;$("time").disabled=objectType!=="block"||!options.length;
 renderEvents();
}
function renderEvents(){
 const root=$("events");root.replaceChildren();const hash=$("object").value;
 if(objectType==="transaction"){
  const tx=data.transactions.find(t=>t.hash===hash);$("time-label").textContent="Receipt observation";$("replay-note").textContent="Sender RPC acceptance and receipt observation only. Per-peer transaction arrival and forwarding are not collected.";
  if(tx){for(const [title,time,text] of [["RPC accepted",tx.accepted_at,tx.node?data.nodes.find(n=>n.id===tx.node)?.label:"Ingress node outside recent tail"],["Receipt observed",tx.receipt_at,tx.status]]){const card=html("div","event");card.append(html("strong","",title),html("span","",time?clock(time):"Not in recent window"),html("small","",text));root.append(card);}explorerLink(root,"tx",tx.hash);}else root.append(html("p","muted","No transaction matches the recent bounded file window."));return;
 }
 const raw=activeEvents().sort((a,b)=>a.at-b.at),firstSeen=new Map();for(const e of raw){const key=e.node+"/"+e.stage;if(!firstSeen.has(key))firstSeen.set(key,e);}const events=[...firstSeen.values()];
 const first=events[0]?.at,last=events.at(-1)?.at,limit=first+(last-first)*replay;
 $("time-label").textContent=events.length?`+${((last-first)*replay).toFixed(3)} s / ${(last-first).toFixed(3)} s`:"No observations";
 $("replay-note").textContent=events.length?`${new Set(events.map(e=>e.node)).size} observed nodes · ${data.mode==="demo"?"SYNTHETIC · ":""}Polled file observations share collector-round timestamps; queried heads use API response times. Neither measures exact message propagation or forwarding paths.`:"No matching events in the recent file tail. Try another slot/hash; full-history indexing is not enabled.";
 events.filter(e=>e.at<=limit).slice(0,60).forEach(e=>{const card=html("div","event");const name=data.nodes.find(n=>n.id===e.node)?.label||e.node;const button=html("button","",name);button.onclick=()=>{const n=data.nodes.find(n=>n.id===e.node);layer="beacon";document.querySelectorAll("[data-layer]").forEach(b=>b.classList.toggle("active",b.dataset.layer===layer));$("asn").value=n?.asn||"all";chooseNode(e.node);};card.append(button,html("strong","",`+${(e.at-first).toFixed(3)} s`),html("small","",e.stage),html("small","","Source peer: unavailable"));root.append(card);});
 if(events.length)explorerLink(root,"slot",events[0].slot);
}
function explorerLink(root,kind,value){if(!data.explorer_url)return;const link=html("a","event","Open in EthExplorer ↗");link.href=`${data.explorer_url}/${kind}/${encodeURIComponent(value)}`;link.target="_blank";link.rel="noopener noreferrer";root.append(link);}
function render(){
 $("mode").textContent=data.mode==="demo"?"SYNTHETIC DEMO":data.mode==="live"?(data.probe_active===undefined?"DEPLOYMENT · PASSIVE":data.fresh?"LIVE · UPDATING":"LIVE · WAITING"):data.collector_status!=="running"?"RECORDED · INACTIVE":data.fresh&&Date.now()/1000-data.sample_at<180?"RECORDED · UPDATING":"RECORDED · STALE";$("mode").classList.toggle("demo",data.mode==="demo");
 $("run").textContent=data.run;renderFreshness();
 const oldChain=$("chain").value;const chains=[...new Set(data.nodes.map(n=>n.chain).filter(Boolean))].sort();$("chain").replaceChildren(new Option("All chains","all"),...chains.map(c=>new Option(c,c)));$("chain").value=chains.includes(oldChain)?oldChain:"all";
 const old=$("asn").value;const asns=[...new Set(data.nodes.map(n=>n.asn))].sort((a,b)=>Number(a)-Number(b));$("asn").replaceChildren(new Option("All AS","all"),...asns.map(a=>new Option(`AS ${a}`,a)));$("asn").value=asns.includes(old)?old:"all";
 $("footer-note").textContent=data.mode==="demo"?"SYNTHETIC DATA · Never use this fixture as experiment evidence.":`Processor: ${data.processor.source}${data.probe_active===false?" (paused)":""} · Queue deltas require two observations. No inferred forwarding paths.`;
 buildObjects();renderGraph();renderDetail();renderComparison();renderNetworkSummary();
}
function renderNetworkSummary(){
 const root=$("network-summary"),s=data.network_summary;root.replaceChildren();
 root.append(html("span","eyebrow","NETWORK WORKLOAD"),html("h2","","Queues & transaction pools"));
 if(!s){root.append(html("p","muted","Summary unavailable from this server."));return;}
 const grid=html("div","summary-grid"),queue=html("article",""),pool=html("article","");
 const p0=s.queues.api_request_p0;
 queue.append(html("h3","","Beacon API P0"));
 addRow(queue,"Mean across sampled Beacon nodes",fmt(p0?.mean,3));
 addRow(queue,"P95 / maximum across nodes",`${fmt(p0?.p95,3)} / ${fmt(p0?.max,3)}`);
 addRow(queue,"Valid sample coverage",`${p0?.count||0} / ${s.beacons_total}`);
 const more=html("details","");more.append(html("summary","","Other queues: mean / P95 / max / coverage"));
 for(const [type,v] of Object.entries(s.queues)){if(type!=="api_request_p0")addRow(more,type,`${fmt(v.mean,3)} / ${fmt(v.p95,3)} / ${fmt(v.max,3)} / ${v.count}`);}
 queue.append(more);
 pool.append(html("h3","","Geth transaction pools"));
 addRow(pool,"Pending copies / queued copies",`${fmt(s.txpool.pending_copies,0)} / ${fmt(s.txpool.queued_copies,0)}`);
 addRow(pool,"Total copies across sampled Geths",fmt(s.txpool.total_copies,0));
 addRow(pool,"Per Geth: mean / P95 / max",`${fmt(s.txpool.per_node.mean,1)} / ${fmt(s.txpool.per_node.p95,0)} / ${fmt(s.txpool.per_node.max,0)}`);
 addRow(pool,"Valid sample coverage",`${s.geths_sampled} / ${s.geths_total}`);
 addRow(pool,"Unique network-wide pending transactions","Not collected (counts alone cannot deduplicate)");
 grid.append(queue,pool);root.append(grid,html("p","muted",`Latest non-simultaneous samples; failed/unknown or older than ${s.max_age_seconds}s excluded, never counted as zero. Queue mean = equal-weight average of node interval means, not instantaneous depth. A transaction held by 100 Geths contributes 100 copies, not 100 unique transactions.`));
}
let snapshotBusy=false,eventBusy=false,eventTag=null,eventCache=null;
function renderFreshness(){
 const peer=data.probe_timing?.peers;
 const latest=Math.max(0,...data.events.map(e=>e.at||0));
 $("freshness").textContent=`Resources ${age(data.sample_at)} · Last block observation ${latest?age(latest):"unavailable"} · Events checked every 2 s${peer?` · Peer sweep ${peer.sweep_seconds.toFixed(2)} s / target ${peer.interval_seconds} s${peer.overrun?" (overrun)":""} · completed ${age(peer.completed_at)}`:""}`;
}
async function refresh(){
 if(paused||snapshotBusy)return;snapshotBusy=true;
 try{const response=await fetch("/api/snapshot",{signal:AbortSignal.timeout(8000)});if(!response.ok)throw new Error(`HTTP ${response.status}`);const next=await response.json();if(paused)return;data=next;if(eventCache&&eventCache.generated_at>data.generated_at)data.events=eventCache.events;render();}
 catch(e){$("freshness").textContent=`Source unavailable: ${e.message}. Last snapshot retained.`;}
 finally{snapshotBusy=false;}
}
async function refreshEvents(){
 if(paused||eventBusy||!data||data.mode==="demo")return;eventBusy=true;
 try{
  const response=await fetch("/api/events",{headers:eventTag?{"If-None-Match":eventTag}:{},signal:AbortSignal.timeout(5000)});
  if(response.status===304){renderFreshness();return;}
  if(!response.ok)throw new Error(`HTTP ${response.status}`);
  const next=await response.json();if(paused)return;
  eventTag=response.headers.get("ETag");eventCache=next;data.events=next.events;
  buildObjects();renderGraph();renderFreshness();
 }catch(e){$("freshness").textContent=`Event feed unavailable: ${e.message}. Last observations retained.`;}
 finally{eventBusy=false;}
}
document.querySelectorAll("[data-layer]").forEach(b=>b.onclick=()=>{layer=b.dataset.layer;focus=false;document.querySelectorAll("[data-layer]").forEach(t=>t.classList.toggle("active",t===b));renderGraph();renderDetail();});
$("asn").onchange=()=>{focus=false;renderGraph();renderDetail();};$("color").onchange=renderGraph;
$("chain").onchange=()=>{focus=false;selected=null;renderGraph();renderDetail();};
$("search").oninput=()=>{if(data){buildObjects();renderGraph();}};
$("clear").onclick=()=>{$("search").value="";$("asn").value="all";$("chain").value="all";selected=null;focus=false;replay=1;$("time").value=1000;render();};
$("object").onchange=()=>{followLatest=false;$("follow").textContent="Follow latest";$("follow").setAttribute("aria-pressed","false");replay=1;$("time").value=1000;renderEvents();renderGraph();};
$("follow").onclick=()=>{followLatest=!followLatest;if(followLatest){replay=1;$("time").value=1000;}buildObjects();renderGraph();};
$("blocks-tab").onclick=()=>{objectType="block";$("blocks-tab").classList.add("active");$("tx-tab").classList.remove("active");buildObjects();renderGraph();};
$("tx-tab").onclick=()=>{objectType="transaction";$("tx-tab").classList.add("active");$("blocks-tab").classList.remove("active");buildObjects();renderGraph();};
$("time").oninput=()=>{replay=Number($("time").value)/1000;renderEvents();renderGraph();};
$("play").onclick=()=>{if(timer){clearInterval(timer);timer=null;$("play").textContent="Play";return;}paused=true;$("freeze").textContent="Resume updates";replay=0;$("play").textContent="Stop";timer=setInterval(()=>{replay=Math.min(1,replay+.025);$("time").value=Math.round(replay*1000);renderEvents();renderGraph();if(replay===1){clearInterval(timer);timer=null;$("play").textContent="Play";}},100);};
$("freeze").onclick=()=>{paused=!paused;$("freeze").textContent=paused?"Resume updates":"Pause updates";if(!paused)refresh();};
$("paper").onclick=()=>{document.body.classList.toggle("figure");$("paper").textContent=document.body.classList.contains("figure")?"Exit figure":"Figure mode";};
$("export").onclick=()=>{if(data)download(`lookingglass-${data.mode}.json`,JSON.stringify(data,null,2),"application/json");};
$("svg-export").onclick=()=>{const svg=$("graph").cloneNode(true);svg.setAttribute("xmlns",NS);svg.setAttribute("font-family","Trebuchet MS, sans-serif");const label=el("text",{x:12,y:18,fill:"#64767b","font-size":10},`${data.mode.toUpperCase()} · ${$("map-title").textContent} · ${$("counts").textContent} · connections are not message paths`);svg.prepend(label);download(`lookingglass-map-${data.mode}.svg`,new XMLSerializer().serializeToString(svg),"image/svg+xml");};
refresh();setInterval(refresh,2000);setInterval(refreshEvents,2000);
let resizeTimer;window.addEventListener("resize",()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(renderGraph,100);});
