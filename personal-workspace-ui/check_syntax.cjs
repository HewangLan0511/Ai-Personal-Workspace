// 语法门禁：提取 index.html 内联 <script>，vm.Script 编译检查
const fs = require('fs'), vm = require('vm');
const html = fs.readFileSync(__dirname + '/index.html', 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.error('FAIL 未找到内联 script'); process.exit(1); }
try {
  new vm.Script(m[1], { filename: 'inline.js' });
  console.log('PASS 语法门禁 (' + m[1].split('\n').length + ' 行 script)');
} catch (e) {
  console.error('FAIL 语法错误: ' + e.message);
  process.exit(1);
}
