import { execFile } from 'node:child_process';
import { readFile, lstat } from 'node:fs/promises';
import { join } from 'node:path';
// Only the Integration credential is decrypted. Browser pairing stays in Core.
const UNPROTECT = `Add-Type -AssemblyName System.Security; $blob=[Console]::In.ReadToEnd(); $bytes=[Convert]::FromBase64String($blob); $plain=[Security.Cryptography.ProtectedData]::Unprotect($bytes,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser); [Console]::Out.Write([Text.Encoding]::UTF8.GetString($plain))`;
export function unprotectWindows(ciphertext) {
    return new Promise((resolve, reject) => {
        const executable = join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
        const child = execFile(executable, ['-NoProfile', '-NonInteractive', '-Command', UNPROTECT], { windowsHide: true, timeout: 5000, maxBuffer: 16384 }, (error, stdout) => {
            if (error)
                reject(new Error('Local credential decryption failed'));
            else
                resolve(stdout);
        });
        child.stdin?.on('error', () => { });
        child.stdin?.end(ciphertext);
    });
}
let cached;
export async function readLocalIntegrationToken(baseUrl, options = {}) {
    const path = options.path || (process.platform === 'win32' && process.env.USERPROFILE
        ? join(process.env.USERPROFILE, '.hku-agents', 'connection-v1.json') : null);
    if (!path)
        return null;
    let file;
    try {
        const stat = await lstat(path);
        if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 16384)
            throw new Error('Invalid credential file');
        file = JSON.parse(await readFile(path, 'utf8'));
    }
    catch (error) {
        if (error.code === 'ENOENT')
            return null;
        throw new Error('Protected local connection unavailable');
    }
    if (file.version !== 1 || typeof file.integration !== 'string' || !/^[A-Za-z0-9+/]+={0,2}$/.test(file.integration))
        throw new Error('Invalid local credentials');
    if (cached && cached.ciphertext === file.integration && cached.baseUrl === baseUrl)
        return cached.token;
    const value = JSON.parse(await (options.decrypt || unprotectWindows)(file.integration));
    if (value.base_url !== baseUrl)
        return null;
    if (typeof value.token !== 'string' || !/^[\x21-\x7e]{32,200}$/.test(value.token))
        throw new Error('Invalid local credentials');
    cached = { ciphertext: file.integration, baseUrl, token: value.token };
    return value.token;
}
//# sourceMappingURL=local_credentials.js.map