// Real React + ReactDOM stateful browser rendering; mock SDK boundary only.
import { register, createRequire } from 'node:module';
import {pathToFileURL} from 'node:url';
import {homedir} from 'node:os';
import {readFileSync} from 'node:fs';
const source=process.env.HERMES_SDK_SOURCE??`${homedir()}/.hermes/hermes-agent`;
const localRequire=createRequire(new URL('package.json',import.meta.url));
let require=localRequire;
try { for(const dependency of ['react','react-dom/client','jsdom'])localRequire.resolve(dependency); }
catch { require=createRequire(`${source}/apps/desktop/package.json`); }
const map=Object.fromEntries(['react','react/jsx-runtime','react-dom/client','jsdom'].map(p=>[p,pathToFileURL(require.resolve(p)).href]));
map['@hermes/plugin-sdk']=new URL('sdk-stub.mjs',import.meta.url).href;
register('data:text/javascript,'+encodeURIComponent(`const map=${JSON.stringify(map)};export async function resolve(s,c,next){if(map[s])return {url:map[s],shortCircuit:true};return next(s,c);}`));
const {JSDOM}=await import('jsdom');
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost'});
globalThis.window=dom.window;globalThis.document=dom.window.document;globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const {act}=await import('react');
const {createRoot}=await import('react-dom/client');
const sdk=await import('./sdk-stub.mjs');
const plugin=(await import(pathToFileURL(process.argv[2]).href)).default;
const sdkSource=readFileSync(`${source}/apps/desktop/src/sdk/index.ts`,'utf8');
const contextSource=readFileSync(`${source}/apps/desktop/src/contrib/plugin.ts`,'utf8');
if(!sdkSource.includes('busy: readonlyAtom<boolean>($focusedBusy)'))throw new Error('Focused busy SDK contract missing');
for(const method of ['focusedSessionId','focusedStoredSessionId','focusedSessionOwner','connectionId','profileRoutes','requestProfile','navigate']) {if(!sdkSource.includes(method))throw new Error(`SDK contract missing ${method}`);}
for(const method of ['onEvent','registerSettingsPage','registerMany','rest']) {if(!contextSource.includes(method))throw new Error(`SDK context missing ${method}`);}
const registered=[];let settings;
const ctx={...sdk.ctx,registerMany:items=>registered.push(...items),registerSettingsPage:page=>{settings=page;}};
plugin.register(ctx);
const manager=registered.find(i=>i.id==='manager');
let root;
const tick=async()=>{await act(async()=>{await new Promise(r=>setTimeout(r,12));});};
const render=async()=>{root=createRoot(document.getElementById('root'));await act(async()=>root.render(manager.render()));await tick();};
const unmount=async()=>{if(root)await act(async()=>root.unmount());root=null;};
const text=()=>document.body.textContent;
const button=label=>[...document.querySelectorAll('button')].find(b=>b.textContent===label||b.getAttribute('aria-label')===label);
const click=async label=>{const b=button(label);if(!b)throw new Error(`Missing button ${label}`);await act(async()=>b.click());await tick();};
const type=async(selector,value)=>{await act(async()=>{const input=document.querySelector(selector);if(!input)throw new Error(`Missing ${selector}`);Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype,'value').set.call(input,value);input.dispatchEvent(new dom.window.Event('input',{bubbles:true}));input.dispatchEvent(new dom.window.Event('change',{bubbles:true}));});};
// React's input tracking requires globals to precede ReactDOM loading.
const formData=async()=>{await click('+ Add Client Key');await type('input:not([type="password"])','New Client');await type('input[type="password"]','synthetic-test-value');};
const scenarios=[];
async function scenario(name,setup=()=>{},action=async()=>{}){await unmount();sdk.reset();await act(async()=>setup());await render();sdk.calls.length=0;await action();scenarios.push({name,calls:structuredClone(sdk.calls),notices:structuredClone(sdk.notices),text:text(),inputs:[...document.querySelectorAll('input')].map(i=>({value:i.value,label:i.getAttribute('aria-label'),type:i.type})),disabled:[...document.querySelectorAll('button')].filter(b=>b.disabled).map(b=>b.textContent),events:sdk.eventCount(),storage:sdk.storage.get('unverified-pending-switches',{})});}
await scenario('accepted',()=>{},()=>click('Use Landal'));
await scenario('preserve-model',()=>sdk.setInfo({model:'gpt-6.1-sol',provider:'bonzai'}),()=>click('Use Landal'));
await scenario('named-client-status',()=>{sdk.setInfo({model:'gpt-6.1-sol',provider:'custom:bonzai-key-landal'});sdk.setSessions({'stored-chat-1':'landal'});});
await scenario('key-model-hidden',()=>sdk.setCredentialsModel('legacy-model'));
await scenario('no-current-model',()=>sdk.setInfo({provider:'bonzai'}),()=>click('Use Landal'));
await scenario('default-selected',()=>sdk.setSessions({'stored-chat-1':'io'}));
await scenario('confirm-required',()=>sdk.rpcResult({confirm_required:true,confirm:'confirmation-token',confirm_message:'Large context input cost'}),()=>click('Use Landal'));
await scenario('confirm-switch',()=>sdk.rpcResult({confirm_required:true,confirm:'confirmation-token',confirm_message:'Large context input cost'}),async()=>{await click('Use Landal');if(button('Switch'))await click('Switch');});
await scenario('confirm-cancel',()=>sdk.rpcResult({confirm_required:true,confirm:'confirmation-token',confirm_message:'Large context input cost'}),async()=>{await click('Use Landal');if(button('Cancel'))await click('Cancel');});
await scenario('confirm-focus-race',()=>sdk.rpcResult({confirm_required:true,confirm:'confirmation-token',confirm_message:'Large context input cost'}),async()=>{await click('Use Landal');const confirm=sdk.buttons.get('Switch');await act(async()=>sdk.setFocused('chat-2'));if(confirm)await act(async()=>confirm.onClick());});
await scenario('rejected',()=>sdk.failRpc('Unknown model alias'),()=>click('Use Landal'));
await scenario('deferred',()=>sdk.rpcResult({key:'model',value:'landal',deferred:true}),()=>click('Use Landal'));
await scenario('foreign-owner',()=>sdk.setOwner({connectionId:'remote',profile:'work'}),async()=>{
 // Invoke retained handlers despite disabled UI to test imperative scope guards.
 const props=sdk.buttons.get('Use Landal')??sdk.buttons.get('Use');if(props?.onClick)await act(async()=>props.onClick());
 const add=sdk.buttons.get('+ Add Client Key');if(add?.onClick)await act(async()=>add.onClick());
});
await scenario('save-focus-race',()=>sdk.setSaveDelay(25),async()=>{await formData();await act(async()=>{
 document.querySelector('form').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}));await new Promise(r=>setTimeout(r,5));sdk.setFocused('chat-2');await new Promise(r=>setTimeout(r,40));});await tick();});
await scenario('profile-secret-clear',()=>{},async()=>{await formData();await act(async()=>{sdk.setProfile('work');sdk.setOwner({connectionId:'local',profile:'work'});});await tick();await click('+ Add Client Key');});
await scenario('rename',()=>{},async()=>{await click('Rename Landal');await type('input','Landal Updated');await click('Save name');});
await scenario('test-stored',()=>{},()=>click('Test Landal'));
await scenario('delete-blocked',()=>sdk.failDelete('This key is selected by a chat (409)'),async()=>{await click('Remove Landal');await click('Remove');});
await scenario('late-foreign-actions',()=>{},async()=>{await click('Rename Landal');await type('input','Changed');const rename=sdk.buttons.get('Save name');const test=sdk.buttons.get('Test Landal');await act(async()=>sdk.setOwner({connectionId:'remote',profile:'work'}));await act(async()=>{await rename.onClick();await test.onClick();});});
await scenario('retained-profile-save',()=>{},async()=>{await formData();const form=document.querySelector('form');const submit=new dom.window.Event('submit',{bubbles:true,cancelable:true});await act(async()=>{sdk.setProfile('work');sdk.setOwner({connectionId:'local',profile:'work'});form.dispatchEvent(submit);});});
await scenario('retained-profile-use',()=>{},async()=>{sdk.setRoutes([{connectionId:'local',mode:'local',profile:'work',targetProfile:'work'}]);const use=sdk.buttons.get('Use Landal');await act(async()=>{sdk.setProfile('work');sdk.setOwner({connectionId:'local',profile:'work'});});await act(async()=>use.onClick());});
await scenario('profile-route-race',()=>{},async()=>{await act(async()=>{const pending=sdk.buttons.get('Use Landal').onClick();sdk.setProfile('work');await pending;});});
await scenario('route-race',()=>{},async()=>{await act(async()=>{const pending=sdk.buttons.get('Use Landal').onClick();sdk.setFocused('chat-2');await pending;});});
await scenario('rpc-race',()=>sdk.setSwitchDelay(20),async()=>{await act(async()=>{const pending=sdk.buttons.get('Use Landal').onClick();await new Promise(r=>setTimeout(r,3));sdk.setFocused('chat-2');await pending;});});
await scenario('foreign-event',()=>{},async()=>{await act(async()=>sdk.emit({type:'session.info',session_id:'chat-1',connectionId:'remote',profile:'default',payload:{model:'gpt-4o',provider:'openai'}}));});
await scenario('pending-remove',()=>sdk.rpcResult({key:'model',value:'landal',deferred:true}),async()=>{await click('Use Landal');const remove=sdk.buttons.get('Remove Landal');await act(async()=>remove.onClick());await click('Remove');});
await scenario('busy-switch',()=>sdk.setBusy(true),async()=>{await act(async()=>sdk.buttons.get('Use Landal').onClick());});
await scenario('busy-save',()=>{},async()=>{await formData();const form=document.querySelector('form');await act(async()=>{sdk.setBusy(true);form.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}));});});
await scenario('busy-route-race',()=>{},async()=>{await act(async()=>{const pending=sdk.buttons.get('Use Landal').onClick();sdk.setBusy(true);await pending;});});
await scenario('pending-clear',()=>sdk.rpcResult({deferred:true}),async()=>{await click('Use Landal');sdk.rpcResult({key:'model',value:'io'});await click('Use iO (Default)');});
await scenario('pending-reload',()=>sdk.rpcResult({deferred:true}),async()=>{await click('Use Landal');await unmount();sdk.clearLocalAtoms();plugin.register(ctx);await render();await click('Remove Landal');await click('Remove');});
await scenario('pending-other-profile',()=>sdk.rpcResult({deferred:true}),async()=>{await click('Use Landal');await act(async()=>{sdk.setProfile('work');sdk.setOwner({connectionId:'local',profile:'work'});});await click('Remove Landal');await click('Remove');});
await scenario('stored-query-mismatch',()=>sdk.setInfo({model:'gpt-4o',provider:'openai',stored_session_id:'other-chat'}));
await scenario('stored-event-mismatch',()=>{},async()=>{await act(async()=>sdk.emit({type:'session.info',session_id:'chat-1',connectionId:'local',profile:'default',payload:{model:'gpt-4o',provider:'openai',stored_session_id:'other-chat'}}));});
await scenario('palette',()=>{},()=>registered.find(i=>i.id==='focus').data.run());
await scenario('inactive',()=>{sdk.setInfo({model:'gpt-4o',provider:'openai',running:false});sdk.setSessions({'stored-chat-1':'landal'});});
await scenario('unknown-key',()=>sdk.setSessions({'stored-chat-1':'landal'}));
await scenario('event-reconcile',()=>{},async()=>{await act(async()=>sdk.emit({type:'session.info',session_id:'chat-1',connectionId:'local',profile:'default',payload:{model:'gpt-4o',provider:'openai',running:false}}));await tick();});
await unmount();
const older=[];plugin.register({...sdk.ctx,registerMany:items=>older.push(...items)});
const olderPalette=older.find(i=>i.id==='focus');sdk.calls.length=0;olderPalette.data.run();
const olderRoute={registered:older.map(i=>i.id),calls:structuredClone(sdk.calls)};
process.stdout.write(JSON.stringify({registered:registered.map(i=>i.id),settings:Boolean(settings),olderRoute,scenarios,eventsAfterUnmount:sdk.eventCount()}));
