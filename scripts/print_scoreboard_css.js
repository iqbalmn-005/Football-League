const fs = require('fs');
const c = fs.readFileSync('front/organizer_index.html', 'utf8');
const lines = c.split('\n');
console.log(lines.slice(3980, 4015).join('\n'));

