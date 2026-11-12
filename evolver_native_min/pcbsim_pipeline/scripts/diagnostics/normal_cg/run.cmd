// This command file is preserved verbatim with every attempted run.
recalc
normal_motion on
conj_grad on
printf "LAB_INITIAL_ENERGY %.17g\n", total_energy
printf "LAB_INITIAL_VOLUME %.17g\n", body[1].volume
g 30
r
g 1000
define vertex attribute lab_x real
define vertex attribute lab_y real
define vertex attribute lab_z real
lab_passes := 0
lab_checks := 0
if lab_passes < 2 then {
set vertex lab_x x;
set vertex lab_y y;
set vertex lab_z z;
lab_old_energy := total_energy;
g 30;
lab_drift := abs(total_energy-lab_old_energy)/(1+abs(total_energy));
lab_move := max(vertex,sqrt((x-lab_x)^2+(y-lab_y)^2+(z-lab_z)^2));
lab_checks += 1;
if lab_drift <= 9.9999999999999995e-08 and lab_move <= 1.0000000000000001e-05 and abs(body[1].volume-0.43219016502150925)/0.43219016502150925 <= 9.9999999999999995e-08 then lab_passes += 1 else lab_passes := 0;
printf "PCS_CHECK %d %.17g %.17g %d\n",lab_checks,lab_drift,lab_move,lab_passes;
}
if lab_passes < 2 then {
if lab_passes == 0 then g 1000;
set vertex lab_x x;
set vertex lab_y y;
set vertex lab_z z;
lab_old_energy := total_energy;
g 30;
lab_drift := abs(total_energy-lab_old_energy)/(1+abs(total_energy));
lab_move := max(vertex,sqrt((x-lab_x)^2+(y-lab_y)^2+(z-lab_z)^2));
lab_checks += 1;
if lab_drift <= 9.9999999999999995e-08 and lab_move <= 1.0000000000000001e-05 and abs(body[1].volume-0.43219016502150925)/0.43219016502150925 <= 9.9999999999999995e-08 then lab_passes += 1 else lab_passes := 0;
printf "PCS_CHECK %d %.17g %.17g %d\n",lab_checks,lab_drift,lab_move,lab_passes;
}
if lab_passes < 2 then {
if lab_passes == 0 then g 1000;
set vertex lab_x x;
set vertex lab_y y;
set vertex lab_z z;
lab_old_energy := total_energy;
g 30;
lab_drift := abs(total_energy-lab_old_energy)/(1+abs(total_energy));
lab_move := max(vertex,sqrt((x-lab_x)^2+(y-lab_y)^2+(z-lab_z)^2));
lab_checks += 1;
if lab_drift <= 9.9999999999999995e-08 and lab_move <= 1.0000000000000001e-05 and abs(body[1].volume-0.43219016502150925)/0.43219016502150925 <= 9.9999999999999995e-08 then lab_passes += 1 else lab_passes := 0;
printf "PCS_CHECK %d %.17g %.17g %d\n",lab_checks,lab_drift,lab_move,lab_passes;
}
if lab_passes < 2 then {
if lab_passes == 0 then g 1000;
set vertex lab_x x;
set vertex lab_y y;
set vertex lab_z z;
lab_old_energy := total_energy;
g 30;
lab_drift := abs(total_energy-lab_old_energy)/(1+abs(total_energy));
lab_move := max(vertex,sqrt((x-lab_x)^2+(y-lab_y)^2+(z-lab_z)^2));
lab_checks += 1;
if lab_drift <= 9.9999999999999995e-08 and lab_move <= 1.0000000000000001e-05 and abs(body[1].volume-0.43219016502150925)/0.43219016502150925 <= 9.9999999999999995e-08 then lab_passes += 1 else lab_passes := 0;
printf "PCS_CHECK %d %.17g %.17g %d\n",lab_checks,lab_drift,lab_move,lab_passes;
}
if lab_passes < 2 then {
if lab_passes == 0 then g 1000;
set vertex lab_x x;
set vertex lab_y y;
set vertex lab_z z;
lab_old_energy := total_energy;
g 30;
lab_drift := abs(total_energy-lab_old_energy)/(1+abs(total_energy));
lab_move := max(vertex,sqrt((x-lab_x)^2+(y-lab_y)^2+(z-lab_z)^2));
lab_checks += 1;
if lab_drift <= 9.9999999999999995e-08 and lab_move <= 1.0000000000000001e-05 and abs(body[1].volume-0.43219016502150925)/0.43219016502150925 <= 9.9999999999999995e-08 then lab_passes += 1 else lab_passes := 0;
printf "PCS_CHECK %d %.17g %.17g %d\n",lab_checks,lab_drift,lab_move,lab_passes;
}
if lab_passes < 2 then {
if lab_passes == 0 then g 1000;
set vertex lab_x x;
set vertex lab_y y;
set vertex lab_z z;
lab_old_energy := total_energy;
g 30;
lab_drift := abs(total_energy-lab_old_energy)/(1+abs(total_energy));
lab_move := max(vertex,sqrt((x-lab_x)^2+(y-lab_y)^2+(z-lab_z)^2));
lab_checks += 1;
if lab_drift <= 9.9999999999999995e-08 and lab_move <= 1.0000000000000001e-05 and abs(body[1].volume-0.43219016502150925)/0.43219016502150925 <= 9.9999999999999995e-08 then lab_passes += 1 else lab_passes := 0;
printf "PCS_CHECK %d %.17g %.17g %d\n",lab_checks,lab_drift,lab_move,lab_passes;
}
if lab_passes < 2 then {
if lab_passes == 0 then g 1000;
set vertex lab_x x;
set vertex lab_y y;
set vertex lab_z z;
lab_old_energy := total_energy;
g 30;
lab_drift := abs(total_energy-lab_old_energy)/(1+abs(total_energy));
lab_move := max(vertex,sqrt((x-lab_x)^2+(y-lab_y)^2+(z-lab_z)^2));
lab_checks += 1;
if lab_drift <= 9.9999999999999995e-08 and lab_move <= 1.0000000000000001e-05 and abs(body[1].volume-0.43219016502150925)/0.43219016502150925 <= 9.9999999999999995e-08 then lab_passes += 1 else lab_passes := 0;
printf "PCS_CHECK %d %.17g %.17g %d\n",lab_checks,lab_drift,lab_move,lab_passes;
}
if lab_passes < 2 then {
if lab_passes == 0 then g 1000;
set vertex lab_x x;
set vertex lab_y y;
set vertex lab_z z;
lab_old_energy := total_energy;
g 30;
lab_drift := abs(total_energy-lab_old_energy)/(1+abs(total_energy));
lab_move := max(vertex,sqrt((x-lab_x)^2+(y-lab_y)^2+(z-lab_z)^2));
lab_checks += 1;
if lab_drift <= 9.9999999999999995e-08 and lab_move <= 1.0000000000000001e-05 and abs(body[1].volume-0.43219016502150925)/0.43219016502150925 <= 9.9999999999999995e-08 then lab_passes += 1 else lab_passes := 0;
printf "PCS_CHECK %d %.17g %.17g %d\n",lab_checks,lab_drift,lab_move,lab_passes;
}
if lab_passes < 2 then {
if lab_passes == 0 then g 1000;
set vertex lab_x x;
set vertex lab_y y;
set vertex lab_z z;
lab_old_energy := total_energy;
g 30;
lab_drift := abs(total_energy-lab_old_energy)/(1+abs(total_energy));
lab_move := max(vertex,sqrt((x-lab_x)^2+(y-lab_y)^2+(z-lab_z)^2));
lab_checks += 1;
if lab_drift <= 9.9999999999999995e-08 and lab_move <= 1.0000000000000001e-05 and abs(body[1].volume-0.43219016502150925)/0.43219016502150925 <= 9.9999999999999995e-08 then lab_passes += 1 else lab_passes := 0;
printf "PCS_CHECK %d %.17g %.17g %d\n",lab_checks,lab_drift,lab_move,lab_passes;
}
if lab_passes < 2 then {
if lab_passes == 0 then g 1000;
set vertex lab_x x;
set vertex lab_y y;
set vertex lab_z z;
lab_old_energy := total_energy;
g 30;
lab_drift := abs(total_energy-lab_old_energy)/(1+abs(total_energy));
lab_move := max(vertex,sqrt((x-lab_x)^2+(y-lab_y)^2+(z-lab_z)^2));
lab_checks += 1;
if lab_drift <= 9.9999999999999995e-08 and lab_move <= 1.0000000000000001e-05 and abs(body[1].volume-0.43219016502150925)/0.43219016502150925 <= 9.9999999999999995e-08 then lab_passes += 1 else lab_passes := 0;
printf "PCS_CHECK %d %.17g %.17g %d\n",lab_checks,lab_drift,lab_move,lab_passes;
}
printf "LAB_CONVERGENCE_CHECKS %.17g\n",lab_checks
printf "LAB_CONVERGENCE_PASSES %.17g\n",lab_passes
printf "LAB_ENERGY %.17g\n", total_energy
printf "LAB_ENERGY_DRIFT %.17g\n", abs(total_energy-lab_old_energy)/(1+abs(total_energy))
printf "LAB_MAX_MOVE %.17g\n", max(vertex,sqrt((x-lab_x)^2+(y-lab_y)^2+(z-lab_z)^2))
printf "LAB_AREA %.17g\n", total_area
printf "LAB_FACETS %d\n", facet_count
printf "LAB_VOLUME %.17g\n", body[1].volume
printf "LAB_PRESSURE %.17g\n", body[1].pressure
foreach vertex vv do printf "LAB_VERTEX %d %.17g %.17g %.17g\n",vv.id,vv.x,vv.y,vv.z
foreach facet ff do printf "LAB_FACE %d %d %d %d\n",ff.id,ff.vertex[1].id,ff.vertex[2].id,ff.vertex[3].id
foreach facet ff do printf "PCS_REGION %d %d\n",ff.id,ff.pcbsim_region
dump "final.dmp"
printf "LAB_COMPLETE 1\n"
quit 0
