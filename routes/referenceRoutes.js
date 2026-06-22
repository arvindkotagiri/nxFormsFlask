import express from 'express';
import pool from '../db.js';

const router = express.Router();

// Helper helper to generate reference routes
const makeRefRoute = (path, tableName) => {
  router.get(path, async (req, res) => {
    try {
      const result = await pool.query(`SELECT id, name FROM ${tableName} ORDER BY name ASC`);
      res.status(200).json(result.rows);
    } catch (err) {
      console.error(`Error fetching reference from ${tableName}:`, err);
      res.status(500).json({ error: err.message });
    }
  });
};

// Map routes to table names
makeRefRoute('/reference/customers', 'ref_customers');
makeRefRoute('/reference/plants', 'ref_plants');
makeRefRoute('/reference/warehouses', 'ref_warehouses');
makeRefRoute('/reference/company-codes', 'ref_company_codes');
makeRefRoute('/reference/sales-orgs', 'ref_sales_orgs');
makeRefRoute('/reference/shipping-points', 'ref_shipping_points');
makeRefRoute('/reference/process-types', 'ref_process_types');

// Custom routes for all-labels (which query label_master)
router.get('/reference/all-labels', async (req, res) => {
  try {
    const result = await pool.query(`
      SELECT DISTINCT label_id AS id, label_name AS name, context 
      FROM label_master 
      ORDER BY label_name ASC
    `);
    res.status(200).json(result.rows);
  } catch (err) {
    console.error('Error fetching labels list:', err);
    res.status(500).json({ error: err.message });
  }
});

// Custom routes for printers (which query printer_master)
router.get('/reference/printers', async (req, res) => {
  try {
    const result = await pool.query(`
      SELECT id, name 
      FROM printer_master 
      ORDER BY name ASC
    `);
    res.status(200).json(result.rows);
  } catch (err) {
    console.error('Error fetching printers list:', err);
    res.status(500).json({ error: err.message });
  }
});

export default router;
