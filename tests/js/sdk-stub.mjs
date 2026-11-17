// SDK boundary only; hooks and rendering use the installed real React.
import React, { useEffect, useState, useSyncExternalStore } from 'react';
export const calls = [], notices = [], buttons = new Map(), queries = new Map();
let state, listeners = new Set(), events = new Set();
const localAtoms=[];
const storageData=new Map();
export const storage={get:(key,fallback)=>storageData.get(key)??fallback,set:(key,value)=>storageData.set(key,structuredClone(value)),remove:key=>storageData.delete(key)};
export const clearLocalAtoms=()=>{for(const a of localAtoms)a.set({});};
const changed = () => { for (const fn of listeners) fn(); };
export function reset() {
  state = { focused: 'chat-1', storedId: 'stored-chat-1', owner: {connectionId:'local',profile:'default'}, connectionId:'local', profile:'default', routes:[{connectionId:'local',mode:'local',profile:'default',targetProfile:'default'}], rpcResult:{key:'model',value:'landal'}, info:{model:'gemini-3.7-flash',provider:'bonzai',running:false}, credentials:[{slug:'io',label:'iO (Default)',configured:true,removable:false,renameable:false},{slug:'landal',label:'Landal',configured:true,removable:true,renameable:true}], sessions:{}, switchDelay:0, saveDelay:0 };
  storageData.clear(); calls.length=0; notices.length=0; buttons.clear(); queries.clear(); for(const a of localAtoms)a.set({}); changed();
}
reset();
export const setFocused = id => { state.focused=id; state.storedId=id?`stored-${id}`:null; changed(); };
export const setOwner = owner => {state.owner=owner; changed();};
export const setProfile = profile => {state.profile=profile; changed();};
export const setRoutes = routes => {state.routes=routes;};
export const setBusy = value => {state.busy=value;changed();};
export const setInfo = info => {state.info=info;};
export const setCredentialsModel = model => {for (const entry of state.credentials) entry.model=model;};
export const setSessions = sessions => {state.sessions=sessions;};
export const setSwitchDelay = ms => {state.switchDelay=ms;};
export const setSaveDelay = ms => {state.saveDelay=ms;};
export const failRpc = message => {state.rpcError=message;};
export const rpcResult = result => {state.rpcResult=result;};
export const failDelete = message => {state.deleteError=message;};
export const emit = event => {for(const fn of events) fn(event);};
export const eventCount = () => events.size;
const readableAtom = read => ({get:read,subscribe:fn=>{listeners.add(fn); return ()=>listeners.delete(fn);}});
export const host = {
  state:{busy:readableAtom(()=>Boolean(state.busy)),focusedSessionId:readableAtom(()=>state.focused),focusedStoredSessionId:readableAtom(()=>state.storedId),focusedSessionOwner:readableAtom(()=>state.owner),connectionId:readableAtom(()=>state.connectionId),profile:readableAtom(()=>state.profile)},
  notify:notice=>notices.push(notice),
  navigate:path=>calls.push({via:'navigate',path}),
  profileRoutes:async()=>{calls.push({via:'routes'});return state.routes;},
  requestProfile:async(route,method,params)=>{
    calls.push({via:'profile-rpc',route,method,params});
    if(method==='session.info') return structuredClone(state.info);
    if(method==='config.set' && params.key==='model') throw new Error('use_session_mutation_model');
    if(state.switchDelay) await new Promise(r=>setTimeout(r,state.switchDelay));
    if(state.rpcError) throw new Error(state.rpcError);
    if(params.confirm==='confirmation-token') return {ok:true};
    return state.rpcResult;
  },
  onEvent:(_type,fn)=>{events.add(fn);return ()=>events.delete(fn);},
};
export async function rest(path,options={}) {
  const method=options.method??'GET';
  calls.push({via:'rest',path,method,body:options.body??null});
  if(path==='/credentials'&&method==='GET') return {credentials:structuredClone(state.credentials)};
  if(path==='/sessions') return {sessions:structuredClone(state.sessions)};
  if(path==='/credentials'&&method==='POST') {
    if(state.saveDelay) await new Promise(r=>setTimeout(r,state.saveDelay));
    const credential={slug:'new-client',label:options.body.label,configured:true,removable:true,renameable:true};
    state.credentials.push(credential); return {credential};
  }
  if(path.endsWith('/route')&&method==='POST') {const slug=path.split('/')[2];return {payload:{model:options.body.model||'gpt-6-luna',provider:slug==='io'?'bonzai':`custom:bonzai-key-${slug}`}};}
  if(path.startsWith('/sessions/')&&method==='POST') {state.sessions[path.split('/')[2]]=options.body.slug;return {slug:options.body.slug};}
  if(path==='/credentials/test-stored') return {ok:true,model_count:2};
  if(method==='DELETE'&&state.deleteError) throw new Error(state.deleteError);
  if(method==='PATCH') {const credential=state.credentials.find(e=>path.endsWith('/'+e.slug));credential.label=options.body.label;return {credential};}
  return {};
}
export function atom(initial) { let value=initial; const subscribers=new Set(); const a={get:()=>value,set:next=>{value=next;for(const fn of subscribers)fn();},subscribe:fn=>{subscribers.add(fn);return ()=>subscribers.delete(fn);}};localAtoms.push(a);return a; }
export const useValue = a => useSyncExternalStore(a.subscribe,a.get,a.get);
export const useQueryClient = () => ({setQueryData:(key,data)=>{const q=queries.get(JSON.stringify(key));if(q){q.value={data,isLoading:false,isSuccess:true,isError:false};for(const fn of q.listeners)fn();}},invalidateQueries:async({queryKey})=>{
  for(const query of queries.values()) if(query.key.slice(0,queryKey.length).every((v,i)=>v===queryKey[i])) await query.fetch();
}});
export function useQuery(options) {
  const key=JSON.stringify(options.queryKey);
  let query=queries.get(key);
  if(!query) {
    query={key:options.queryKey,listeners:new Set(),value:{data:undefined,isLoading:true,isSuccess:false,isError:false}};
    query.fetch=async()=>{try {query.value={data:await options.queryFn(),isLoading:false,isSuccess:true,isError:false};} catch(error){query.value={error,isLoading:false,isSuccess:false,isError:true};} for(const fn of query.listeners) fn();};
    queries.set(key,query);
  }
  const value=useSyncExternalStore(fn=>{query.listeners.add(fn);return ()=>query.listeners.delete(fn);},()=>query.value);
  useEffect(()=>{if(options.enabled!==false) {query.fetch(); if(options.refetchInterval){const t=setInterval(query.fetch,options.refetchInterval);return ()=>clearInterval(t);}}},[key,options.enabled]);
  return {...value,refetch:query.fetch};
}
const component = tag => function Component({children,...props}) {return React.createElement(tag,props,children);};
export const Badge=component('span'), ScrollArea=component('div'), Separator=component('hr');
export function Button({children,variant,size,...props}) {buttons.set(props['aria-label']??children,props); return React.createElement('button',props,children);}
export function Input(props) {return React.createElement('input',props);}
export function StatusDot({tone}) {return React.createElement('span',{'data-tone':tone});}
export function GlyphSpinner() {return React.createElement('span',null,'Loading…');}
export function EmptyState({title,description}) {return React.createElement('div',null,title,description);}
export const ErrorState=EmptyState;
export function ConfirmDialog({open,onConfirm,onClose,title,description,confirmLabel}) {return open?React.createElement('div',{role:'dialog'},title,description,React.createElement('button',{onClick:onConfirm},confirmLabel),React.createElement('button',{onClick:onClose},'Cancel')):null;}
export const PALETTE_AREA='palette',PANES_AREA='panes',ROUTES_AREA='routes',STATUSBAR_AREAS={right:'statusbar.right'};
export const pluginSettingsHref = plugin => `/settings?tab=plugins&plugin=${encodeURIComponent(plugin)}`;
export const ctx={storage,rest,registerMany:()=>{},onEvent:host.onEvent};
