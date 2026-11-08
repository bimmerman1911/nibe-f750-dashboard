import fs from 'node:fs';

const diagram=fs.readFileSync(new URL('../src/nibe-f750-card.js',import.meta.url),'utf8');
const smart=fs.readFileSync(new URL('../dist/nibe-f750-smart-card.js',import.meta.url),'utf8');
// Block scope keeps the two cards' helpers separate. The standalone planner
// retains its exports for Node tests; the HACS bundle registers both cards.
const bundle=diagram+'\n// Smart Control included in the single HACS resource.\n{\n'+smart.replace(/^export /gm,'')+'\n}\n';
const target=new URL('../dist/nibe-f750-card.js',import.meta.url);
if(process.argv.includes('--check')) {
  if(fs.readFileSync(target,'utf8')!==bundle)throw Error('Run npm run build to update the HACS bundle.');
} else fs.writeFileSync(target,bundle);
