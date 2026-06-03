import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';

import { initSettingsDb } from './routes/settingsRoutes.js';
import { initImageDb } from './routes/imageRetentionRoutes.js';

// Route imports
import dbRoutes from './routes/dbRoutes.js';
import labelRoutes from './routes/labelRoutes.js';
import settingsRoutes from './routes/settingsRoutes.js';
import printerRoutes from './routes/printerRoutes.js';
import apiMasterRoutes from './routes/apiMasterRoutes.js';
import imageRetentionRoutes from './routes/imageRetentionRoutes.js';
import analyzeRoutes from './routes/analyze.js';
import generateZplRoutes from './routes/generateZpl.js';
import generateXdpRoutes from './routes/generateXdp.js';
import replicateInvoiceRoutes from './routes/replicateInvoice.js';

dotenv.config();

const app = express();
const PORT = process.env.PORT || 5000;

// Request logging middleware to track API processes
app.use((req, res, next) => {
  const start = Date.now();
  const timestamp = new Date().toISOString();
  console.log(`[${timestamp}] >>> Incoming Request: ${req.method} ${req.originalUrl}`);
  res.on('finish', () => {
    const duration = Date.now() - start;
    console.log(`[${timestamp}] <<< Response: ${req.method} ${req.originalUrl} - Status: ${res.statusCode} (${duration}ms)`);
  });
  next();
});


// CORS setup matching Flask
app.use(cors({
  origin: true,
  credentials: true
}));

// Body parsers with 100MB limit (fixes HTTP 413)
app.use(express.json({ limit: '100mb' }));
app.use(express.urlencoded({ limit: '100mb', extended: true }));

// Serve static files (crops, temp files)
app.use('/static', express.static('static'));

// Mount routes matching Flask blueprints and prefixes
app.use('/', dbRoutes);
app.use('/', labelRoutes);
app.use('/', settingsRoutes);
app.use('/', analyzeRoutes);
app.use('/', generateZplRoutes);
app.use('/', generateXdpRoutes);
app.use('/', replicateInvoiceRoutes);

app.use('/api', printerRoutes);
app.use('/api', apiMasterRoutes);
app.use('/api', imageRetentionRoutes);

// Global Error Handler
app.use((err, req, res, next) => {
  console.error("Unhandled Server Error:", err);
  res.status(500).json({ error: err.message });
});

// Initialize database tables and start listening
async function startServer() {
  try {
    await initSettingsDb();
    await initImageDb();
    
    app.listen(PORT, () => {
      console.log(`\n==================================================`);
      console.log(`[SERVER] NodeJS/Express server listening on port ${PORT}`);
      console.log(`==================================================\n`);
    });
  } catch (err) {
    console.error("[CRITICAL ERROR] Server failed to start:", err);
    process.exit(1);
  }
}

startServer();
