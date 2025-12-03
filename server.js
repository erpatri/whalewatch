const fs = require('fs');
const path = require('path');

const UPLOAD_DIR = path.join(__dirname, 'uploads'); // same as before

app.get('/debug/videos', (req, res) => {
  fs.readdir(UPLOAD_DIR, (err, files) => {
    if (err) {
      console.error('Error reading uploads folder:', err);
      return res.status(500).send('Error reading uploads folder');
    }

    const rows = files.map(f => {
      const fullPath = path.join(UPLOAD_DIR, f);
      let size = 0;
      try {
        size = fs.statSync(fullPath).size;
      } catch (e) {
        console.error('stat error for', fullPath, e);
      }
      return { name: f, size };
    });

    const html = `
      <h1>Uploaded videos</h1>
      <table border="1" cellpadding="6">
        <tr><th>File</th><th>Size (bytes)</th><th>Link</th></tr>
        ${rows.map(r =>
          `<tr>
            <td>${r.name}</td>
            <td>${r.size}</td>
            <td><a href="/videos/${r.name}" target="_blank">open</a></td>
          </tr>`
        ).join('')}
      </table>
    `;
    res.send(html);
  });
});
