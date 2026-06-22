import express from 'express';
import pool from '../db.js';

const router = express.Router();

// Initialize the database table
export async function initLabelConfigDb() {
  const client = await pool.connect();
  try {
    await client.query(`
      CREATE TABLE IF NOT EXISTS label_configs (
        config_id SERIAL PRIMARY KEY,
        label_name TEXT NOT NULL,
        label_id TEXT NOT NULL,
        customer TEXT,
        plant TEXT,
        company_code TEXT,
        sales_organization TEXT,
        warehouse TEXT,
        shipping_point TEXT,
        process_type TEXT,
        number_of_labels INTEGER DEFAULT 1,
        priority INTEGER DEFAULT 10,
        active BOOLEAN DEFAULT TRUE,
        valid_from DATE,
        valid_to DATE,
        printer TEXT,
        custom_fields JSONB,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      );
    `);
    console.log("[INIT] label_configs table verified/created in database");
  } catch (err) {
    console.error("[INIT ERROR] Failed to initialize label configs database:", err);
  } finally {
    client.release();
  }
}

// 1. GET /label-configs
router.get('/label-configs', async (req, res) => {
  try {
    const result = await pool.query("SELECT * FROM label_configs ORDER BY priority ASC, created_at DESC");
    res.status(200).json(result.rows);
  } catch (err) {
    console.error("Error fetching label configs:", err);
    res.status(500).json({ error: err.message });
  }
});

// 2. GET /label-configs/:id
router.get('/label-configs/:id', async (req, res) => {
  const { id } = req.params;
  try {
    const result = await pool.query("SELECT * FROM label_configs WHERE config_id = $1", [id]);
    if (result.rows.length === 0) {
      return res.status(404).json({ error: "Label config not found" });
    }
    res.status(200).json(result.rows[0]);
  } catch (err) {
    console.error("Error fetching label config:", err);
    res.status(500).json({ error: err.message });
  }
});

// 3. POST /label-configs
router.post('/label-configs', async (req, res) => {
  try {
    const data = req.body || {};
    const query = `
      INSERT INTO label_configs (
        label_name, label_id, customer, plant, company_code, sales_organization, 
        warehouse, shipping_point, process_type, number_of_labels, priority, 
        active, valid_from, valid_to, printer, custom_fields
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
      RETURNING config_id;
    `;

    const values = [
      data.label_name,
      data.label_id,
      data.customer || null,
      data.plant || null,
      data.company_code || null,
      data.sales_organization || null,
      data.warehouse || null,
      data.shipping_point || null,
      data.process_type || null,
      data.number_of_labels !== undefined ? parseInt(data.number_of_labels, 10) : 1,
      data.priority !== undefined ? parseInt(data.priority, 10) : 10,
      data.active !== undefined ? Boolean(data.active) : true,
      data.valid_from || null,
      data.valid_to || null,
      data.printer || null,
      JSON.stringify(data.custom_fields || {})
    ];

    const result = await pool.query(query, values);
    res.status(201).json({ status: "success", config_id: result.rows[0].config_id });
  } catch (err) {
    console.error("Error creating label config:", err);
    res.status(500).json({ error: err.message });
  }
});

// 4. PUT /label-configs/:id
router.put('/label-configs/:id', async (req, res) => {
  const { id } = req.params;
  try {
    const data = req.body || {};
    const query = `
      UPDATE label_configs
      SET 
        label_name = $1, 
        label_id = $2, 
        customer = $3, 
        plant = $4, 
        company_code = $5, 
        sales_organization = $6, 
        warehouse = $7, 
        shipping_point = $8, 
        process_type = $9, 
        number_of_labels = $10, 
        priority = $11, 
        active = $12, 
        valid_from = $13, 
        valid_to = $14, 
        printer = $15, 
        custom_fields = $16
      WHERE config_id = $17
    `;

    const values = [
      data.label_name,
      data.label_id,
      data.customer || null,
      data.plant || null,
      data.company_code || null,
      data.sales_organization || null,
      data.warehouse || null,
      data.shipping_point || null,
      data.process_type || null,
      data.number_of_labels !== undefined ? parseInt(data.number_of_labels, 10) : 1,
      data.priority !== undefined ? parseInt(data.priority, 10) : 10,
      data.active !== undefined ? Boolean(data.active) : true,
      data.valid_from || null,
      data.valid_to || null,
      data.printer || null,
      JSON.stringify(data.custom_fields || {}),
      id
    ];

    await pool.query(query, values);
    res.status(200).json({ status: "success" });
  } catch (err) {
    console.error("Error updating label config:", err);
    res.status(500).json({ error: err.message });
  }
});

// 5. DELETE /label-configs/:id
router.delete('/label-configs/:id', async (req, res) => {
  const { id } = req.params;
  try {
    await pool.query("DELETE FROM label_configs WHERE config_id = $1", [id]);
    res.status(200).json({ status: "success" });
  } catch (err) {
    console.error("Error deleting label config:", err);
    res.status(500).json({ error: err.message });
  }
});

// 6. POST /label-determination
router.post('/label-determination', async (req, res) => {
  try {
    const payload = req.body || {};
    const query = "SELECT * FROM label_configs WHERE active = true ORDER BY priority ASC";
    const result = await pool.query(query);
    const configs = result.rows;

    const matched = [];
    for (const rule of configs) {
      let isMatch = true;

      // Match static fields if defined in the rule
      if (rule.company_code && payload.company_code !== rule.company_code) isMatch = false;
      if (rule.sales_organization && payload.sales_organization !== rule.sales_organization) isMatch = false;
      if (rule.plant && payload.plant !== rule.plant) isMatch = false;
      if (rule.warehouse && payload.warehouse !== rule.warehouse) isMatch = false;
      if (rule.customer && payload.customer !== rule.customer) isMatch = false;
      if (rule.process_type && payload.process_type !== rule.process_type) isMatch = false;
      if (rule.shipping_point && payload.shipping_point !== rule.shipping_point) isMatch = false;

      // Match dynamic conditions inside custom_fields JSONB
      if (isMatch && rule.custom_fields && typeof rule.custom_fields === 'object') {
        for (const [k, v] of Object.entries(rule.custom_fields)) {
          if (v && payload[k] !== v) {
            isMatch = false;
            break;
          }
        }
      }

      if (isMatch) {
        matched.push({
          label_name: rule.label_name,
          label_id: rule.label_id,
          number_of_labels: rule.number_of_labels,
          priority: rule.priority,
          printer: rule.printer
        });
      }
    }

    res.status(200).json({
      match_count: matched.length,
      labels: matched
    });
  } catch (err) {
    console.error("Error in label determination:", err);
    res.status(500).json({ error: err.message });
  }
});

export default router;
