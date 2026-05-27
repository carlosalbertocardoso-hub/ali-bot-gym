# Configurar tareas programadas para el bot de gimnasio
# Ejecutar como Administrador

$scriptPath = "C:\Users\ccard\Proyectos\gym-bot-alicia\gym_bot.py"
$workingDir = Split-Path -Parent $scriptPath
$pythonPath = "C:\Users\ccard\AppData\Local\Programs\Python\Python312\python.exe"

# Tarea 1: Domingo 22:00 → reserva Body Tono del lunes 18:00
$task1 = @{
    TaskName = "GymBot-BodyTono-Lunes"
    Action = New-ScheduledTaskAction -Execute $pythonPath -Argument "`"$scriptPath`"" -WorkingDirectory $workingDir
    Trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Sunday -At 22:00
    Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Principal = New-ScheduledTaskPrincipal -UserId "ccard" -RunLevel Highest
}

# Tarea 2: Martes 22:00 → reserva Body Tono del miércoles 18:00
$task2 = @{
    TaskName = "GymBot-BodyTono-Miercoles"
    Action = New-ScheduledTaskAction -Execute $pythonPath -Argument "`"$scriptPath`"" -WorkingDirectory $workingDir
    Trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Tuesday -At 22:00
    Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Principal = New-ScheduledTaskPrincipal -UserId "ccard" -RunLevel Highest
}

# Tarea 3: Miércoles 22:00 → reserva POWER del jueves 19:00
$task3 = @{
    TaskName = "GymBot-POWER-Jueves"
    Action = New-ScheduledTaskAction -Execute $pythonPath -Argument "`"$scriptPath`"" -WorkingDirectory $workingDir
    Trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Wednesday -At 22:00
    Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Principal = New-ScheduledTaskPrincipal -UserId "ccard" -RunLevel Highest
}

Write-Host "Creando tareas programadas..."
try {
    Register-ScheduledTask @task1 -Force
    Write-Host "✅ GymBot-BodyTono-Lunes (Dom 22:00)"
} catch { Write-Warning "BodyTono-Lunes: $_" }

try {
    Register-ScheduledTask @task2 -Force
    Write-Host "✅ GymBot-BodyTono-Miercoles (Mar 22:00)"
} catch { Write-Warning "BodyTono-Miercoles: $_" }

try {
    Register-ScheduledTask @task3 -Force
    Write-Host "✅ GymBot-POWER-Jueves (Mié 22:00)"
} catch { Write-Warning "POWER-Jueves: $_" }

Write-Host ""
Write-Host "Ver tareas: Get-ScheduledTask -TaskName GymBot-*"
