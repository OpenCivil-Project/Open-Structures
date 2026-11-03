#!/usr/bin/env node
/* Operator-only provider repair. Never package this tool or OAuth credentials. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');

const TARGET = 'openstructures-b3f46';
const VERIFIED_PROJECT = 'opencivil';
const VERIFIED_NUMBER = '250654468779';
const HANDLER = 'https://openstructures-b3f46.firebaseapp.com/__/auth/handler';
const ENDPOINT = `/projects/${TARGET}/defaultSupportedIdpConfigs/google.com`;

function fail(message) { throw Object.assign(new Error(message), {safeMessage:message}); }
function readWebCredentials(file) {
  const raw = fs.readFileSync(file, 'utf8');
  if (Buffer.byteLength(raw) > 32768) fail('OAuth configuration is too large.');
  const data = JSON.parse(raw);
  const web = data.web;
  if (!web || data.installed) fail('Use a Web application OAuth client from opencivil, not a Desktop client.');
  if (web.project_id !== VERIFIED_PROJECT ||
      !new RegExp(`^${VERIFIED_NUMBER}-[a-zA-Z0-9_-]+\\.apps\\.googleusercontent\\.com$`).test(web.client_id || '')) {
    fail('The Web client must belong to the already verified opencivil project.');
  }
  if (typeof web.client_secret !== 'string' || web.client_secret.length < 10 || web.client_secret.length > 512) {
    fail('The downloaded Web OAuth configuration is missing its client secret.');
  }
  if (!Array.isArray(web.redirect_uris) || !web.redirect_uris.includes(HANDLER)) {
    fail(`Add this redirect URI to the Web client before downloading its JSON: ${HANDLER}`);
  }
  return {clientId:web.client_id,clientSecret:web.client_secret,enabled:true};
}

function protect(data) {
  const script = "Add-Type -AssemblyName System.Security; $bytes=[Text.Encoding]::UTF8.GetBytes([Console]::In.ReadToEnd()); $protected=[Security.Cryptography.ProtectedData]::Protect($bytes,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser); [Console]::Out.Write([Convert]::ToBase64String($protected))";
  const result = spawnSync('powershell.exe',['-NoProfile','-NonInteractive','-Command',script],
    {input:JSON.stringify(data),encoding:'utf8',windowsHide:true,maxBuffer:65536});
  if (result.status !== 0 || !/^[A-Za-z0-9+/=]+$/.test(result.stdout || '')) fail('Could not encrypt the operator rollback configuration. No provider change was made.');
  return Buffer.from(result.stdout,'base64');
}

function unprotect(file) {
  const script = "Add-Type -AssemblyName System.Security; $bytes=[Convert]::FromBase64String([Console]::In.ReadToEnd()); $plain=[Security.Cryptography.ProtectedData]::Unprotect($bytes,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser); [Console]::Out.Write([Text.Encoding]::UTF8.GetString($plain))";
  const result=spawnSync('powershell.exe',['-NoProfile','-NonInteractive','-Command',script],
    {input:fs.readFileSync(file).toString('base64'),encoding:'utf8',windowsHide:true,maxBuffer:65536});
  if (result.status !== 0) fail('The rollback file could not be decrypted by this Windows account.');
  return JSON.parse(result.stdout);
}

function saveBackup(file, data) {
  const absolute = path.resolve(file);
  const encrypted = protect(data);
  fs.writeFileSync(absolute,encrypted,{flag:'wx',mode:0o600});
  const identity=spawnSync('whoami.exe',[],{encoding:'utf8',windowsHide:true});
  const account=identity.stdout.trim();
  const acl=spawnSync('icacls.exe',[absolute,'/inheritance:r','/grant:r',`${account}:(F)`,'SYSTEM:(F)'],{encoding:'utf8',windowsHide:true});
  if (identity.status !== 0 || acl.status !== 0) fail('Could not restrict the encrypted rollback file. No provider change was made.');
  return absolute;
}

async function connect() {
  const candidates=[
    path.join(process.env.LOCALAPPDATA || '', 'Packages','OpenAI.Codex_2p2nqsd0c76g0','LocalCache','Roaming','npm','node_modules','firebase-tools','lib'),
    path.join(process.env.APPDATA || '', 'npm','node_modules','firebase-tools','lib'),
  ];
  const cli=candidates.find(candidate=>fs.existsSync(path.join(candidate,'auth.js')));
  if (!cli) fail('Firebase CLI could not be found.');
  const auth=require(path.join(cli,'auth.js'));
  const account=auth.getGlobalDefaultAccount();
  if (!account) fail('Sign in with firebase login first.');
  await require(path.join(cli,'requireAuth.js')).requireAuth({...account,nonInteractive:true,project:TARGET});
  const {Client}=require(path.join(cli,'apiv2.js'));
  return new Client({urlPrefix:'https://identitytoolkit.googleapis.com/admin',apiVersion:'v2'});
}

async function patch(client, data) {
  await client.request({method:'PATCH',path:ENDPOINT,
    queryParams:{updateMask:'clientId,clientSecret,enabled'},body:data,
    skipLog:{body:true,resBody:true}});
}

async function applyAndVerify(client, desired, previous) {
  const current=(await client.get(ENDPOINT,{skipLog:{resBody:true}})).body;
  if (current.clientId !== previous.clientId || current.clientSecret !== previous.clientSecret || current.enabled !== previous.enabled) {
    fail('The live Google provider changed during preparation; no configuration was overwritten.');
  }
  try {
    await patch(client,desired);
    const after=(await client.get(ENDPOINT,{skipLog:{resBody:true}})).body;
    if (after.clientId !== desired.clientId || after.clientSecret !== desired.clientSecret || after.enabled !== true) throw new Error('READBACK_MISMATCH');
    return after;
  } catch (error) {
    let live;
    try { live=(await client.get(ENDPOINT,{skipLog:{resBody:true}})).body; }
    catch (_) { fail('Provider status could not be checked. Keep the encrypted backup and use --rollback after connectivity returns.'); }
    if (live.clientId === desired.clientId) {
      try { await patch(client,previous); }
      catch (_) { fail('The provider update could not be verified and automatic rollback failed. Use the encrypted --rollback backup.'); }
      fail('Provider verification failed; the previous configuration was restored.');
    }
    if (live.clientId === previous.clientId) fail('The provider change failed; the previous configuration remains active.');
    fail('The live provider was changed by another operation; refusing to overwrite it. Keep the encrypted rollback backup.');
  }
}

async function main(args) {
  const value=flag=>{const i=args.indexOf(flag);return i>=0?args[i+1]:null;};
  if (args.includes('--help') || args.length === 0) {
    console.log('Check current provider: node tools/reuse_verified_google_provider.cjs --check\nPrepare: --credentials PATH_TO_WEB_OAUTH_JSON\nApply: --credentials PATH_TO_WEB_OAUTH_JSON --apply --backup ABSOLUTE_BACKUP_FILE\nRollback: --rollback ABSOLUTE_BACKUP_FILE --apply');
    return;
  }
  const credentials=value('--credentials');
  const rollback=value('--rollback');
  if (credentials && rollback) fail('Choose credentials or rollback, not both.');
  const desired=credentials?readWebCredentials(credentials):null;
  const client=await connect();
  const before=(await client.get(ENDPOINT,{skipLog:{resBody:true}})).body;
  if (args.includes('--check')) {
    console.log(JSON.stringify({project:TARGET,googleEnabled:before.enabled,clientId:before.clientId,verifiedProjectClient:before.clientId?.startsWith(VERIFIED_NUMBER+'-')},null,2));
    return;
  }
  if (rollback) {
    const saved=unprotect(rollback);
    if (saved.project !== TARGET || saved.newClientId !== before.clientId) fail('The live provider changed since this backup; refusing to overwrite it.');
    if (!args.includes('--apply')) { console.log(JSON.stringify({action:'rollback',project:TARGET,clientId:saved.previous.clientId,dryRun:true}));return; }
    await patch(client,saved.previous);
    console.log(JSON.stringify({action:'rollback',project:TARGET,restored:true}));
    return;
  }
  if (!desired) fail('Provide a downloaded Web OAuth configuration with --credentials.');
  if (!args.includes('--apply')) {
    console.log(JSON.stringify({project:TARGET,action:'reuse_verified_google_project',oldClientId:before.clientId,newClientId:desired.clientId,dryRun:true,accountsMoved:false},null,2));return;
  }
  const backup=value('--backup');
  if (!backup || !path.isAbsolute(backup)) fail('Specify an absolute --backup path outside the repository.');
  const repository=path.resolve(__dirname,'..');
  const relative=path.relative(repository,path.resolve(backup));
  if (relative === '' || (!relative.startsWith('..'+path.sep) && !path.isAbsolute(relative))) fail('Keep the encrypted operator backup outside the repository.');
  const previous={clientId:before.clientId,clientSecret:before.clientSecret,enabled:before.enabled};
  if (!previous.clientSecret) fail('The current provider secret could not be read; cannot prepare a safe rollback.');
  const saved=saveBackup(backup,{project:TARGET,newClientId:desired.clientId,previous});
  const after=await applyAndVerify(client,desired,previous);
  console.log(JSON.stringify({project:TARGET,googleEnabled:true,clientId:after.clientId,accountsMoved:false,rollback:saved},null,2));
}

if (require.main === module) main(process.argv.slice(2)).catch(error=>{
  console.error(error.safeMessage || 'Provider repair failed. No credentials are included in this diagnostic.');
  process.exitCode=1;
});
module.exports={readWebCredentials,applyAndVerify,protect,unprotect};
