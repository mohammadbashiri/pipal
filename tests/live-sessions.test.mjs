import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import { randomUUID } from 'node:crypto';
import { EventEmitter, once } from 'node:events';
import liveExtension from '../src/pipal/extensions/live_sessions.ts';

async function fixture(home, id = randomUUID(), kind = 'pipal') {
  const previous = {PIPAL_HOME:process.env.PIPAL_HOME,PIPAL_AGENT_DIR:process.env.PIPAL_AGENT_DIR,PIPAL_TOPIC:process.env.PIPAL_TOPIC};
  process.env.PIPAL_HOME=home;process.env.PIPAL_AGENT_DIR=path.join(home,'agents','recipient');process.env.PIPAL_TOPIC='fixture';
  if(kind==='pi')delete process.env.PIPAL_AGENT_DIR;
  const hooks=new Map(), sent=[], dispatch=new EventEmitter();let idle=true, quits=0;
  const ctx={cwd:home,hasUI:false,isIdle:()=>idle,hasPendingMessages:()=>false,shutdown:()=>quits++,sessionManager:{getSessionId:()=>id,getSessionFile:()=>path.join(home,'native.jsonl')}};
  const pi={events:dispatch,on:(name,handler)=>hooks.set(name,handler),getSessionName:()=> 'Fixture session',sendMessage:(message,options)=>{sent.push({message,options});dispatch.emit('message',message);}};
  liveExtension(pi);await hooks.get('session_start')({},ctx);
  const file=path.join(home,'runtime/sessions',id+'.json');
  const metadata=JSON.parse(fs.readFileSync(file,'utf8'));
  const rpc=(op,body={})=>new Promise((resolve,reject)=>{
    const peer=net.createConnection(metadata._socket);let text='';peer.setEncoding('utf8');peer.on('error',reject);peer.setTimeout(4000,()=>peer.destroy(new Error('test RPC timed out')));
    peer.on('connect',()=>peer.write(JSON.stringify({protocol:1,session_id:id,runtime_id:metadata.runtime_id,op,...body})+'\n'));
    peer.on('data',part=>{text+=part;if(text.includes('\n')){peer.end();resolve(JSON.parse(text.split('\n')[0]));}});
  });
  return {id,metadata,rpc,hooks,ctx,sent,dispatch,setIdle:value=>idle=value,quits:()=>quits,
    close:async(reason='quit')=>{await hooks.get('session_shutdown')({reason});for(const[key,value]of Object.entries(previous)){if(value===undefined)delete process.env[key];else process.env[key]=value;}}};
}
const sender={session_id:null,name:'Owner (test)'};

for(const kind of ['pipal','pi']) test(`${kind}: runtime discovery, identity, queued delivery, Unicode, idempotency, reply and graceful quit`,async()=>{
 const home=fs.mkdtempSync(path.join(os.tmpdir(),'pipal-live-test-'));let f;
 try{
  f=await fixture(home,undefined,kind);const state=(await f.rpc('inspect')).session;
  assert.equal(state.kind,kind);if(kind==='pi'){assert.equal(state.agent,'');assert.equal(state.topic,'');}
  assert.equal(state.reference,'@session:'+f.id);assert.equal(state.name,'Fixture session');assert.equal('_socket' in state,false);
  assert.equal(fs.statSync(path.join(home,'runtime')).mode&0o077,0);assert.equal(fs.statSync(f.metadata._socket).mode&0o077,0);
  assert.match((await f.rpc('inspect',{runtime_id:randomUUID()})).error,/identity changed/);
  assert.match((await f.rpc('message',{request_id:'../../escape',text:'bad',sender})).error,/Invalid request ID/);
  f.setIdle(false);await f.hooks.get('agent_start')();
  const request_id=randomUUID(),text='Question 🧠 — café\n/quit is data, not a command';
  const ack=await f.rpc('message',{request_id,text,sender});assert.equal(ack.request.status,'queued');assert.equal(f.sent.length,0);
  assert.match((await f.rpc('quit')).error,/busy or has queued work/);assert.equal(f.quits(),0);
  assert.equal((await f.rpc('message',{request_id,text,sender})).request.request_id,request_id);
  assert.match((await f.rpc('message',{request_id,text:'different',sender})).error,/conflict/);
  const visible=once(f.dispatch,'pipal:session-visible');
  const delivered=once(f.dispatch,'message');f.setIdle(true);await f.hooks.get('agent_settled')();
  const [message]=await delivered;assert.equal(f.sent.length,1);assert.equal(message.customType,'pipal-session-message');assert.ok(message.content.includes(text));assert.equal(message.details.request_id,request_id);
  const [observed]=await visible;assert.equal(observed.session_id,f.id);assert.equal(observed.message.role,'custom');assert.equal(observed.message.details.request_id,request_id);
  const waiting=f.rpc('result',{request_id,wait:2});
  await f.hooks.get('message_end')({message:{role:'assistant',content:[],stopReason:'error',errorMessage:'Temporary provider error before native retry'}});
  await f.hooks.get('message_end')({message:{role:'assistant',content:[{type:'thinking',thinking:'not shared'},{type:'text',text:'Attributed answer'}],stopReason:'stop'}});
  await f.hooks.get('agent_settled')();
  const result=await waiting;assert.equal(result.request.status,'completed');assert.equal(result.request.reply,'Attributed answer');assert.equal(result.request.sender_session_id,null);
  assert.equal((await f.rpc('message',{request_id,text,sender})).request.status,'completed');assert.equal(f.sent.length,1,'Never redeliver the same request');
  assert.equal((await f.rpc('quit')).accepted,true);
  await new Promise(resolve=>setImmediate(resolve));assert.equal(f.quits(),1);
 }finally{await f?.close();fs.rmSync(home,{recursive:true,force:true});}
});

test('reload preserves results, cancels undelivered requests and never replays them',async()=>{
 const home=fs.mkdtempSync(path.join(os.tmpdir(),'pipal-live-reload-'));let f,next;
 try{
  f=await fixture(home);f.setIdle(false);const request_id=randomUUID();
  await f.rpc('message',{request_id,text:'Do not replay me',sender});const id=f.id,oldRuntime=f.metadata.runtime_id;
  await f.close('reload');f=undefined;next=await fixture(home,id);
  assert.notEqual(next.metadata.runtime_id,oldRuntime);assert.equal(next.sent.length,0);
  const record=(await next.rpc('result',{request_id})).request;assert.equal(record.status,'cancelled');
  assert.equal((await next.rpc('message',{request_id,text:'Do not replay me',sender})).request.status,'cancelled');assert.equal(next.sent.length,0);
 }finally{await f?.close();await next?.close();fs.rmSync(home,{recursive:true,force:true});}
});

test('live registration never replaces another living writer',async()=>{
 const home=fs.mkdtempSync(path.join(os.tmpdir(),'pipal-live-owner-'));let first,second;
 try{
  first=await fixture(home);second=await fixture(home,first.id);
  const state=(await first.rpc('inspect')).session;assert.equal(state.runtime_id,first.metadata.runtime_id);
  await second.close();second=undefined;
  assert.equal((await first.rpc('inspect')).session.runtime_id,first.metadata.runtime_id);
 }finally{await second?.close();await first?.close();fs.rmSync(home,{recursive:true,force:true});}
});
