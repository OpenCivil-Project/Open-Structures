'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {readWebCredentials,applyAndVerify,protect,unprotect}=require('../reuse_verified_google_provider.cjs');
const previous={clientId:'previous-public-client',clientSecret:'previous-test-value',enabled:true};
const desired={clientId:'new-public-client',clientSecret:'new-test-value',enabled:true};
function config(web) {
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'opencivil-provider-test-'));
  const file=path.join(dir,'dummy.json');
  fs.writeFileSync(file,JSON.stringify(web));
  return {file,cleanup:()=>fs.rmSync(dir,{recursive:true})};
}
function webClient() {
  return {web:{project_id:'opencivil',client_id:'250654468779-example.apps.googleusercontent.com',
    client_secret:'dummy-for-validation-only',redirect_uris:['https://openstructures-b3f46.firebaseapp.com/__/auth/handler']}};
}
test('refuses a Desktop client before contacting the cloud',()=>{
  const data=config({installed:webClient().web});
  try {assert.throws(()=>readWebCredentials(data.file),/Web application/);} finally {data.cleanup();}
});
test('requires the verified project and exact Firebase callback',()=>{
  const wrongProject=webClient();wrongProject.web.project_id='another-project';
  const missingCallback=webClient();missingCallback.web.redirect_uris=['https://example.com/'];
  for (const value of [wrongProject,missingCallback]) {
    const data=config(value);
    try {assert.throws(()=>readWebCredentials(data.file));} finally {data.cleanup();}
  }
});
test('valid Web metadata prepares only the three provider fields',()=>{
  const data=config(webClient());
  try {assert.deepEqual(Object.keys(readWebCredentials(data.file)).sort(),['clientId','clientSecret','enabled']);} finally {data.cleanup();}
});
test('successful update reads the provider back',async()=>{
  let live={...previous};
  const client={get:async()=>({body:{...live}}),request:async request=>{
    assert.equal(request.skipLog.body,true);
    assert.equal(request.skipLog.resBody,true);
    live={...request.body};
  }};
  assert.deepEqual(await applyAndVerify(client,desired,previous),desired);
});
test('readback failure restores the previous provider',async()=>{
  let live={...previous},gets=0;
  const writes=[];
  const client={get:async()=>{gets++;if(gets===2)throw new Error('network');return {body:{...live}};},
    request:async request=>{writes.push(request.body.clientId);live={...request.body};}};
  await assert.rejects(applyAndVerify(client,desired,previous),/previous configuration was restored/);
  assert.deepEqual(writes,[desired.clientId,previous.clientId]);
  assert.deepEqual(live,previous);
});
test('client secret mismatch also restores the previous provider',async()=>{
  let live={...previous};
  const client={get:async()=>({body:{...live}}),request:async request=>{
    live={...request.body};
    if(live.clientId===desired.clientId)live.clientSecret='incorrect-value';
  }};
  await assert.rejects(applyAndVerify(client,desired,previous),/previous configuration was restored/);
  assert.deepEqual(live,previous);
});
test('does not overwrite a concurrent provider change',async()=>{
  let writes=0;
  const client={get:async()=>({body:{...previous,clientId:'someone-else'}}),request:async()=>{writes++;}};
  await assert.rejects(applyAndVerify(client,desired,previous),/changed during preparation/);
  assert.equal(writes,0);
});
test('operator backup is encrypted by Windows DPAPI', {skip:process.platform!=='win32'},()=>{
  const data=config({});
  try {
    const encrypted=protect({previous});
    assert.equal(encrypted.includes(Buffer.from(previous.clientSecret)),false);
    fs.writeFileSync(data.file,encrypted);
    assert.deepEqual(unprotect(data.file),{previous});
  } finally {data.cleanup();}
});
