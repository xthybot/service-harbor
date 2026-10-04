/* Pure browser/Node validation shared by login and bounded JSON imports. */
(() => {
  const MAX_IMPORT_BYTES = 1024 * 1024;
  const tooLarge = () => new Error('Configuration file is too large (maximum 1 MiB).');
  function validatePassword(value, policy) {
    const points = Array.from(value);
    if (points.length < policy.min_length || points.length > policy.max_length || points.some(char => policy.forbidden_ranges.some(([low,high]) => char.codePointAt(0)>=low && char.codePointAt(0)<=high))) throw new Error(policy.message);
    return value;
  }
  async function readBounded(stream) {
    const reader = stream.getReader();
    const decoder = new TextDecoder('utf-8', {fatal:true});
    let size=0, text='';
    try {
      while (true) {
        const {done,value}=await reader.read();
        if(done)break;
        size += value.byteLength;
        if(size>MAX_IMPORT_BYTES)throw tooLarge();
        text += decoder.decode(value,{stream:true});
      }
      return text + decoder.decode();
    } catch(error) { await reader.cancel().catch(()=>{}); throw error; }
    finally { reader.releaseLock(); }
  }
  function stringifyBounded(value) {
    const text=JSON.stringify(value);
    if(new TextEncoder().encode(text).byteLength>MAX_IMPORT_BYTES)throw tooLarge();
    return text;
  }
  let policyPromise;
  function passwordPolicy() {
    if(!policyPromise)policyPromise=fetch('/static/password-policy.json').then(response=>{
      if(!response.ok)throw new Error('Could not load password rules. Please retry.');
      return response.json();
    }).catch(error=>{policyPromise=null;throw error;});
    return policyPromise;
  }
  const api={MAX_IMPORT_BYTES,validatePassword,readBounded,stringifyBounded,passwordPolicy};
  if(typeof module !== 'undefined' && module.exports)module.exports=api;
  else window.HostInputLimits=api;
})();
