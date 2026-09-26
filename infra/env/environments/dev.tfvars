# dev: cost-minimized, one task, disposable data
# (docs/CLOUD-DEVOPS-DESIGN.md §6.4, §6.6).

app_cpu           = 512 # 0.5 vCPU for api + web together
app_memory        = 1024
app_desired_count = 1

db_instance_class        = "db.t4g.micro"
db_allocated_storage_gb  = 20
db_multi_az              = false
db_backup_retention_days = 1
db_deletion_protection   = false
db_skip_final_snapshot   = true

alb_deletion_protection = false
log_retention_days      = 14
secret_recovery_days    = 0
