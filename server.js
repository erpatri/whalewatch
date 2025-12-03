// server.js
import express from "express";
import multer from "multer";
import cors from "cors";
import path from "path";

const app = express();
const upload = multer({ dest: "uploads/" });

app.use(cors());
app.use(express.json());

app.post("/track", upload.single("video"), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).send("No video file uploaded.");
    }

    const fakeStreamUrl = "https://example.com/your-processed-video.mp4";

    res.json({ stream_url: fakeStreamUrl });
  } catch (err) {
    console.error(err);
    res.status(500).send("Error processing video.");
  }
});

const PORT = process.env.PORT || 10000;
app.listen(PORT, () => {
  console.log(`Server listening on port ${PORT}`);
});
