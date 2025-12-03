// server.js

const express = require('express');
const cors = require('cors');
const multer = require('multer');
const path = require('path');
const fs = require('fs');

// ---- APP SETUP ----
const app = express();
const PORT = process.env.PORT || 10000;

// Allow your local/frontend origin (you can tighten this later)
app.use(cors({ origin: '*' }));

// ---- UPLOAD DIRECTORY ----
const UPLOAD_DIR = path.join(__dirname, 'uploads');
if (!fs.existsSync(UPLOAD_DIR)) {
  fs.mkdirSync(UPLOAD_DIR, { recursive: true });
}

// ---- MULTER CONFIG ----
const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    cb(null, UPLOAD_DIR);
  },
  filename: (req, file, cb) => {
    const unique = Date.now() + '-' + Math.round(Math.random() * 1e9);
    const ext = path.extname(file.originalname) || '.mp4';
    cb(null, unique + ext);
  }
});

const upload = multer({
  storage,
  limits: {
    fileSize: 500 * 1024 * 1024 // 500 MB
  },
  fileFilter: (req, file, cb) => {
    if (!file.mimetype.startsWith('video/')) {
      return cb(new Error('Only video uploads are allowed'));
    }
    cb(null, true);
  }
});

// ---- SERVE UPLOADED VIDEOS ----
// e.g. https://whalewatch.onrender.com/videos/<filename>.mp4
app.use('/videos', express.static(UPLOAD_DIR));

// ---- DEBUG PAGE TO SEE FILES ON RENDER ----
// https://whalewatch.onrender.com/debug/videos
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
        <tr><th>File</th><th>Size (bytes)</th><th>Links</th></tr>
        ${rows.map(r =>
          `<tr>
            <td>${r.name}</td>
            <td>${r.size}</td>
            <td>
              <a href="/videos/${r.name}" target="_blank">open</a> |
              <a href="/download/${r.name}">download</a>
            </td>
          </tr>`
        ).join('')}
      </table>
    `;
    res.send(html);
  });
});

// ---- RAW FILE DOWNLOAD ROUTE ----
// https://whalewatch.onrender.com/download/<filename>
app.get('/download/:name', (req, res) => {
  const filename = req.params.name;
  const filePath = path.join(UPLOAD_DIR, filename);

  if (!fs.existsSync(filePath)) {
    return res.status(404).send('File not found');
  }

  res.download(filePath, filename, (err) => {
    if (err) {
      console.error('Error sending file for download:', err);
      if (!res.headersSent) {
        res.status(500).send('Error downloading file');
      }
    }
  });
});

// ---- MAIN /track ENDPOINT ----
// This is what your frontend calls with the FormData
app.post('/track', upload.single('video'), (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: 'No video uploaded' });
    }

    console.log('Uploaded file:', {
      originalname: req.file.originalname,
      mimetype: req.file.mimetype,
      size: req.file.size,
      filename: req.file.filename
    });

    const streamUrl = `/videos/${req.file.filename}`;
    res.json({ stream_url: streamUrl });
  } catch (err) {
    console.error('Error in /track:', err);
    res.status(500).json({ error: 'Server error while processing video' });
  }
});

// ---- HEALTH CHECK ----
app.get('/', (req, res) => {
  res.send('WhaleWatch backend is running');
});

// ---- START SERVER ----
app.listen(PORT, () => {
  console.log(`Server listening on port ${PORT}`);
});
