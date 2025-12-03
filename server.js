// server.js

const express = require('express');
const cors = require('cors');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

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
    fileSize: 2 * 1024 * 1024 * 1024 // 2GB
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

// ---- HELPER: RUN PYTHON TRACKER ON A VIDEO ----
function runTrackerOnVideo(inputPath, baseName, res) {
  const pythonScript = path.join(__dirname, 'beluga_track_server.py');

  const trackedVideoFilename = baseName + '_tracked.mp4';
  const csvFilename = baseName + '_tracking.csv';

  const trackedVideoPath = path.join(UPLOAD_DIR, trackedVideoFilename);
  const csvPath = path.join(UPLOAD_DIR, csvFilename);

  const pyArgs = [pythonScript, inputPath, trackedVideoPath, csvPath];
  console.log('Running Python tracker:', pyArgs.join(' '));

  // Try 'python' first; if logs later say ENOENT, switch to 'python3'
  const py = spawn('python', pyArgs, { cwd: __dirname });

  let pyStdout = '';
  let pyStderr = '';

  py.stdout.on('data', (data) => {
    const text = data.toString();
    pyStdout += text;
    console.log('[python]', text.trim());
  });

  py.stderr.on('data', (data) => {
    const text = data.toString();
    pyStderr += text;
    console.error('[python err]', text.trim());
  });

  py.on('error', (err) => {
    console.error('Failed to start Python process:', err);
    if (!res.headersSent) {
      return res
        .status(500)
        .json({ error: 'Failed to start whale tracking process', details: String(err) });
    }
  });

  py.on('close', (code) => {
    if (code !== 0) {
      console.error('Python tracker exited with code', code, pyStderr);
      if (!res.headersSent) {
        // send back stderr so you can see the real Python error in the browser dev tools
        return res.status(500).json({
          error: 'Error running whale tracking on server',
          details: pyStderr.slice(0, 2000) || `exit code ${code}`
        });
      }
      return;
    }

    console.log('Tracking complete. Video:', trackedVideoPath, 'CSV:', csvPath);

    const streamUrl = `/videos/${trackedVideoFilename}`;
    const videoDownloadUrl = `/download/${trackedVideoFilename}`;
    const csvDownloadUrl = `/download/${csvFilename}`;

    if (!res.headersSent) {
      res.json({
        stream_url: streamUrl,
        video_url: videoDownloadUrl,
        csv_url: csvDownloadUrl
      });
    }
  });
}


// ---- MAIN /track ENDPOINT ----
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

    const inputPath = req.file.path; // e.g. uploads/12345.mp4
    const baseName = path.parse(req.file.filename).name;
    const ext = path.extname(req.file.originalname).toLowerCase();

    // If it's already an MP4, skip ffmpeg and go straight to tracking
    if (ext === '.mp4') {
      console.log('MP4 upload detected, skipping ffmpeg. Running tracker...');
      return runTrackerOnVideo(inputPath, baseName, res);
    }

    // Otherwise convert to mp4, then run tracker on the converted file
    const outputFilename = baseName + '_converted.mp4';
    const outputPath = path.join(UPLOAD_DIR, outputFilename);

    const ffmpegArgs = [
      '-y',
      '-i', inputPath,
      '-vf', 'scale=720:-2',
      '-c:v', 'libx264',
      '-preset', 'superfast',
      '-crf', '25',
      '-c:a', 'aac',
      '-b:a', '96k',
      '-movflags', '+faststart',
      outputPath
    ];

    console.log('Running ffmpeg:', ffmpegArgs.join(' '));
    const ffmpeg = spawn('ffmpeg', ffmpegArgs);

    ffmpeg.stderr.on('data', (data) => {
      console.log('[ffmpeg]', data.toString());
    });

    ffmpeg.on('close', (code) => {
      if (code !== 0) {
        console.error('ffmpeg exited with code', code);
        return res.status(500).json({ error: 'Error converting video on server' });
      }

      console.log('ffmpeg finished, output:', outputPath);
      const convertedBaseName = path.parse(outputFilename).name;
      runTrackerOnVideo(outputPath, convertedBaseName, res);
    });

  } catch (err) {
    console.error('Error in /track:', err);
    res.status(500).json({ error: 'Server error while processing video' });
  }
});

// ---- HEALTH CHECK ----
app.get('/', (req, res) => {
  res.send('WhaleWatch backend is running (YOLO tracker enabled)');
});

// ---- START SERVER ----
app.listen(PORT, () => {
  console.log(`Server listening on port ${PORT}`);
});
