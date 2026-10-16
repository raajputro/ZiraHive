// Every text the web app shows through tr()/t() needs a Bangla entry in src/locales/bn.ts,
// with the same {placeholders}. Run: npm run check:i18n
const ts=require("typescript"),fs=require("fs");
const files=require("child_process").execSync("find src -name '*.tsx' -o -name '*.ts'").toString().trim().split("\n");
const keys=new Set();
for(const f of files){const sf=ts.createSourceFile(f,fs.readFileSync(f,"utf8"),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const v=n=>{if(ts.isCallExpression(n)&&["tr","t"].includes(n.expression.getText(sf))&&n.arguments[0]&&(ts.isStringLiteral(n.arguments[0])||ts.isNoSubstitutionTemplateLiteral(n.arguments[0])))keys.add(n.arguments[0].text);ts.forEachChild(n,v)};v(sf)}
const src=fs.readFileSync("src/locales/bn.ts","utf8");
const body=src.slice(src.indexOf("const bn"));
const dict=eval("("+body.slice(body.indexOf("{"), body.lastIndexOf("};")+1)+")");
let bad=0;
const missing=[...keys].filter(k=>!(k in dict));
if(missing.length){bad=1;console.error("Missing Bangla for:\n  "+missing.join("\n  "));}
for (const [k,v] of Object.entries(dict)) { const a=(k.match(/\{\w+\}/g)||[]).sort().join(), b=(v.match(/\{\w+\}/g)||[]).sort().join(); if(a!==b) {bad=1;console.error("Placeholders differ:", k, "->", v);} }
console.log(`${keys.size} texts checked`);
process.exit(bad);
