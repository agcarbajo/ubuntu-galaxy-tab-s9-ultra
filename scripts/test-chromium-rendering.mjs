import {spawn} from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
const root=process.argv[3];
const label=process.argv[2];
if(!root || !['wayland-gl','wayland-vulkan','x11-gl','wayland-native'].includes(label)) throw Error('Usage: node test-chromium-rendering.mjs MODE OUTPUT_DIRECTORY');
await fs.mkdir(root,{recursive:true});
await fs.copyFile(new URL('./fixtures/chromium-rendering.html',import.meta.url),path.join(root,'probe.html'));
const profile=await fs.mkdtemp(path.join(root,label+'-'));
let errors='';
const env={...process.env};
delete env.force_gl_vendor; delete env.force_gl_renderer;
if(label==='wayland-native'){env.force_gl_vendor='freedreno';env.force_gl_renderer='FD740';}
const child=spawn(process.env.CHROME_BINARY || '/usr/bin/google-chrome',['--app=file://'+root+'/probe.html','--ozone-platform='+(label==='x11-gl'?'x11':'wayland'),'--use-angle='+(label==='wayland-vulkan'?'vulkan':'gl'),'--no-first-run','--no-default-browser-check','--disable-background-networking','--remote-debugging-port=0','--user-data-dir='+profile,'--window-size=1000,900'],{env,stdio:['ignore','ignore','pipe']});
child.stderr.on('data',b=>errors+=b);
const delay=ms=>new Promise(r=>setTimeout(r,ms));
let sockets=[];
async function connect(url){
 const ws=new WebSocket(url);sockets.push(ws);
 await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
 let id=0;const pending=new Map();
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(pending.has(m.id)){pending.get(m.id)(m);pending.delete(m.id);}};
 return async(method,params={})=>{const n=++id;const p=new Promise(resolve=>pending.set(n,resolve));ws.send(JSON.stringify({id:n,method,params}));return Promise.race([p,delay(10000).then(()=>{throw Error('CDP timeout '+method);})]);};
}
try{
 let portInfo;
 for(let i=0;i<100;i++){try{portInfo=await fs.readFile(path.join(profile,'DevToolsActivePort'),'utf8');break;}catch{await delay(100);}}
 if(!portInfo)throw Error('No debugging endpoint');
 const [port,browserPath]=portInfo.trim().split('\n');
 const browser=await connect('ws://127.0.0.1:'+port+browserPath);
 const info=await browser('SystemInfo.getInfo');
 await fs.writeFile(path.join(root,label+'-gpu.json'),JSON.stringify(info,null,2));
 const tabs=await (await fetch('http://127.0.0.1:'+port+'/json/list')).json();
 const target=tabs.find(t=>t.url.includes('probe.html'));
 if(!target)throw Error('No probe target');
 const page=await connect(target.webSocketDebuggerUrl);
 await delay(12000);
 const dom=await page('Runtime.evaluate',{expression:'document.getElementById("result").textContent',returnByValue:true});
 console.log(label,JSON.stringify(dom));
 const shot=await page('Page.captureScreenshot',{format:'png'});
 if(shot.result?.data)await fs.writeFile(path.join(root,label+'-window.png'),Buffer.from(shot.result.data,'base64'));
 console.log(label,'shader_errors',(errors.match(/Skia shader compilation error/g)||[]).length,'overlap_errors',(errors.match(/overlapping component/g)||[]).length);
 await browser('Browser.close');
}finally{
 for(const ws of sockets)ws.close();
 child.kill('SIGTERM');
 await fs.writeFile(path.join(root,label+'-stderr.log'),errors);
}
