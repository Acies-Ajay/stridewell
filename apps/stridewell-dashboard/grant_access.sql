-- Run as the catalog/schema owner or another principal allowed to grant access.
-- Replace APP_SERVICE_PRINCIPAL_ID everywhere with the app service principal's
-- application/client ID from app Authorization details, NOT the app resource ID.
-- Change sw_dev_ajay if your actual catalog differs.
GRANT USE CATALOG ON CATALOG sw_dev_ajay TO `APP_SERVICE_PRINCIPAL_ID`;
GRANT USE SCHEMA ON SCHEMA sw_dev_ajay.gold TO `APP_SERVICE_PRINCIPAL_ID`;
GRANT USE SCHEMA ON SCHEMA sw_dev_ajay.silver TO `APP_SERVICE_PRINCIPAL_ID`;
GRANT SELECT ON TABLE sw_dev_ajay.gold.daily_sales TO `APP_SERVICE_PRINCIPAL_ID`;
GRANT SELECT ON TABLE sw_dev_ajay.gold.daily_inventory TO `APP_SERVICE_PRINCIPAL_ID`;
GRANT SELECT ON TABLE sw_dev_ajay.gold.stock_cover TO `APP_SERVICE_PRINCIPAL_ID`;
GRANT SELECT ON TABLE sw_dev_ajay.silver.quarantine_pos_sales TO `APP_SERVICE_PRINCIPAL_ID`;
GRANT SELECT ON TABLE sw_dev_ajay.silver.quarantine_ecom_events TO `APP_SERVICE_PRINCIPAL_ID`;
GRANT USE SCHEMA ON SCHEMA sw_dev_ajay.ops TO `APP_SERVICE_PRINCIPAL_ID`;
GRANT SELECT ON TABLE sw_dev_ajay.ops.recon_exceptions TO `APP_SERVICE_PRINCIPAL_ID`;
-- Add warehouse Can use through App resources; it is separate from these grants.
