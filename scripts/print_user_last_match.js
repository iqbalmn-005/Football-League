const fs = require('fs');
const c = fs.readFileSync('front/user_dashboard.html', 'utf8');
const lines = c.split('\n');
console.log(lines.slice(2985, 3045).join('\n'));

