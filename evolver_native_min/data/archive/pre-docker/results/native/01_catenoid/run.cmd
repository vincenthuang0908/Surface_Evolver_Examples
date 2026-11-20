// This command file is preserved verbatim with every attempted run.
recalc
printf "LAB_INITIAL_ENERGY %.17g\n", total_energy
g 30
r
u
g 200
r
u
g 200
define vertex attribute lab_x real
define vertex attribute lab_y real
define vertex attribute lab_z real
set vertex lab_x x
set vertex lab_y y
set vertex lab_z z
lab_old_energy := total_energy
g 200
printf "LAB_ENERGY %.17g\n", total_energy
printf "LAB_ENERGY_DRIFT %.17g\n", abs(total_energy-lab_old_energy)/(1+abs(total_energy))
printf "LAB_MAX_MOVE %.17g\n", max(vertex,sqrt((x-lab_x)^2+(y-lab_y)^2+(z-lab_z)^2))
printf "LAB_AREA %.17g\n", total_area
printf "LAB_FACETS %d\n", facet_count
foreach vertex vv do printf "LAB_VERTEX %d %.17g %.17g %.17g\n",vv.id,vv.x,vv.y,vv.z
foreach facet ff do printf "LAB_FACE %d %d %d %d\n",ff.id,ff.vertex[1].id,ff.vertex[2].id,ff.vertex[3].id
dump "final.dmp"
printf "LAB_COMPLETE 1\n"
quit 0
