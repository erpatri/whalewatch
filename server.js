const express = require('express');
const cors = require('cors');
const multer = require('multer');
const path = require('path');
const fs = require('fs');

// ==== CONFIG ====

const app = express();
const PORT = process.env.PORT || 10000;

// 1) CORS – allow your static-site origin
// In dev you can use '*' while testing
app.use(cors({
  origin: '*', // change this to your static site's URL once deployed
}));

// 2) Make sure we have an uploads folder
const UPLOAD_DIR = path.join(__dirname, 'uploads');
if (!fs.existsSync(UPLOAD_DIR)) {
  fs.mkdirSync(UPLOAD_DIR, { recursive: true });
}

// 3) Multer storage config: save videos to /uploads
const storage = multer.diskStorage({
  destination: function (req, file, cb) {
    cb(null, UPLOAD_DIR);
  },
  filename: function (req, file, cb) {
    const unique = Date.now() + '-' + Math.round(Math.random() * 1e9);
    const ext = path.extname(file.originalname);
    cb(null, unique + ext);
  }
});

const upload = multer({
  storage,
  limits: {
    fileSize: 500 * 1024 * 1024 // 500 MB – adjust as needed
  },
  fileFilter: (req, file, cb) => {
    if (!file.mimetype.startsWith('video/')) {
      return cb(new Error('Only video uploads are allowed'));
    }
    cb(null, true);
  }
});

// 4) Serve uploaded files statically, e.g. https://api.../videos/filename.mp4
app.use('/videos', express.static(UPLOAD_DIR));

// 5) Your /track endpoint
app.post('/track', upload.single('video'), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: 'No video uploaded' });
    }

    // Full path on disk (on Render this will be ephemeral unless you attach a disk)
    const filepath = req.file.path;
    const filename = req.file.filename;

    // TODO: run your whale-tracking model on `filepath` here

    // For now: make up a stream URL that points to the raw uploaded video
    const streamUrl = `/videos/${filename}`;

    // Your frontend expects JSON with stream_url
    res.json({ stream_url: streamUrl });

  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Server error while processing video' });
  }
});

// Simple health check
app.get('/', (req, res) => {
  res.send('WhaleWatch backend is running');
});

app.listen(PORT, () => {
  console.log(`Server listening on port ${PORT}`);
});
