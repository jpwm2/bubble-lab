from __future__ import annotations
from dataclasses import asdict, dataclass
import hashlib, json, math

TWO_PI=2*math.pi

@dataclass(frozen=True)
class MultimodeRimBreakupConfig:
    azimuthal_cells:int=192
    outer_radius_m:float=1.0
    initial_mean_hole_radius_m:float=0.1
    hole_asymmetry_fraction:float=0.08
    hole_asymmetry_mode:int=2
    film_thickness_m:float=1e-3
    density_kg_m3:float=1.0
    dynamic_viscosity_pa_s:float=1e-5
    surface_tension_n_m:float=5e-4
    disturbance_modes:tuple[int,...]=(7,10)
    disturbance_amplitudes:tuple[float,...]=(0.018,0.026)
    disturbance_phases_rad:tuple[float,...]=(0.25,1.10)
    rim_drag_coefficient:float=1.0
    time_step_s:float=1e-4
    max_time_s:float=0.6
    ligament_amplitude_fraction:float=0.10
    detachment_neck_radius_ratio:float=0.50
    partition_neck_radius_ratio:float=0.90

    def __post_init__(self):
        if self.azimuthal_cells<64 or self.azimuthal_cells%2: raise ValueError('azimuthal_cells must be even >=64')
        if not (0<self.initial_mean_hole_radius_m<self.outer_radius_m): raise ValueError('bad radius')
        if not (0<self.hole_asymmetry_fraction<0.25): raise ValueError('bad asymmetry')
        if self.hole_asymmetry_mode<2: raise ValueError('bad asym mode')
        if len(self.disturbance_modes)<2 or len(set(self.disturbance_modes))!=len(self.disturbance_modes): raise ValueError('need >=2 unique modes')
        if len(self.disturbance_amplitudes)!=len(self.disturbance_modes) or len(self.disturbance_phases_rad)!=len(self.disturbance_modes): raise ValueError('mode tuple mismatch')
        if any(m<2 or m>=self.azimuthal_cells//3 for m in self.disturbance_modes): raise ValueError('mode out of supported band')
        if any(a<=0 or a>=0.08 for a in self.disturbance_amplitudes): raise ValueError('bad amplitudes')
        for name in ('outer_radius_m','initial_mean_hole_radius_m','film_thickness_m','density_kg_m3','surface_tension_n_m','time_step_s','max_time_s'):
            v=float(getattr(self,name))
            if not math.isfinite(v) or v<=0: raise ValueError(name)
        if self.dynamic_viscosity_pa_s<0 or not math.isfinite(self.dynamic_viscosity_pa_s): raise ValueError('viscosity')
        if not 0<self.ligament_amplitude_fraction<0.8: raise ValueError('ligament')
        if not 0<self.detachment_neck_radius_ratio<self.partition_neck_radius_ratio<1: raise ValueError('neck thresholds')
    @property
    def dtheta(self): return TWO_PI/self.azimuthal_cells
    @property
    def taylor_culick_speed_m_s(self): return math.sqrt(2*self.surface_tension_n_m/(self.density_kg_m3*self.film_thickness_m))

@dataclass(frozen=True)
class Sample:
    time_s:float; mean_hole_radius_m:float; retraction_speed_m_s:float; mean_tube_radius_m:float
    min_tube_radius_m:float; max_tube_radius_m:float; total_amplitude_fraction:float; neck_radius_ratio:float
    mode_amplitudes:tuple[tuple[int,float],...]; liquid_volume_relative_error:float

@dataclass(frozen=True)
class Droplet:
    id:str; volume_m3:float; mass_kg:float; equivalent_radius_m:float; centroid_angle_rad:float
    position_m:tuple[float,float]; velocity_m_s:tuple[float,float]; momentum_kg_m_s:tuple[float,float]
    source_start_cell:int; source_end_cell:int

@dataclass(frozen=True)
class Result:
    config:MultimodeRimBreakupConfig; samples:tuple[Sample,...]; ligament_onset_time_s:float; detachment_time_s:float
    final_mean_hole_radius_m:float; final_retraction_speed_m_s:float; final_volume_per_radian_m3:tuple[float,...]
    final_tangential_velocity_m_s:tuple[float,...]; initial_mode_amplitudes:tuple[tuple[int,float],...]
    final_mode_amplitudes:tuple[tuple[int,float],...]; neck_cells:tuple[int,...]; droplets:tuple[Droplet,...]
    initial_liquid_volume_m3:float; remaining_film_volume_m3:float; pre_detachment_rim_volume_m3:float; droplet_volume_m3:float
    liquid_volume_relative_error:float; scalar_radial_momentum_kg_m_s:float; capillary_impulse_n_s:float; viscous_impulse_n_s:float
    radial_momentum_residual_kg_m_s:float; solver_digest:str; provenance:dict[str,object]

@dataclass
class State:
    time_s:float; mean_hole_radius_m:float; radial_momentum:float; deviations:list[float]; u:list[float]; cap_imp:float; visc_imp:float

def _hole_geometry(mean_radius,cfg):
    th=[(i+0.5)*cfg.dtheta for i in range(cfg.azimuthal_cells)]
    e=cfg.hole_asymmetry_fraction; k=cfg.hole_asymmetry_mode
    a=[mean_radius*(1+e*math.cos(k*t)) for t in th]
    da=[-mean_radius*e*k*math.sin(k*t) for t in th]
    metric=[math.sqrt(ai*ai+dai*dai) for ai,dai in zip(a,da)]
    return th,a,metric

def _baseline_w(mean_radius,cfg):
    _,a,_=_hole_geometry(mean_radius,cfg)
    return [0.5*cfg.film_thickness_m*ai*ai for ai in a]

def _geometry(st,cfg):
    th,a,metric=_hole_geometry(st.mean_hole_radius_m,cfg)
    base=_baseline_w(st.mean_hole_radius_m,cfg)
    w=[b+d for b,d in zip(base,st.deviations)]
    if min(w)<=0: raise RuntimeError('non-positive rim volume density')
    area=[wi/li for wi,li in zip(w,metric)]
    r=[math.sqrt(x/math.pi) for x in area]
    mean=math.fsum(r)/len(r)
    return th,a,metric,w,r,mean

def _film_rim_volume(st,cfg):
    _,a,_,w,_,_=_geometry(st,cfg)
    hole_area=0.5*math.fsum(ai*ai for ai in a)*cfg.dtheta
    film=(math.pi*cfg.outer_radius_m**2-hole_area)*cfg.film_thickness_m
    rim=math.fsum(w)*cfg.dtheta
    return film+rim,film,rim

def _rp_rate(cfg,mode,mean_hole,mean_tube):
    q=mode*mean_tube/mean_hole
    if q<=0 or q>=1: return 0.0
    return math.sqrt(cfg.surface_tension_n_m/(2*cfg.density_kg_m3*mean_tube**3)*q*q*(1-q*q))

def _mode_amps(radii,modes,cfg):
    mean=math.fsum(radii)/len(radii)
    f=[r/mean-1 for r in radii]
    out=[]
    for m in modes:
        c=2/len(f)*math.fsum(v*math.cos(m*(i+0.5)*cfg.dtheta) for i,v in enumerate(f))
        s=2/len(f)*math.fsum(v*math.sin(m*(i+0.5)*cfg.dtheta) for i,v in enumerate(f))
        out.append((m,math.hypot(c,s)))
    return tuple(out)

def _initial_state(cfg):
    mean=cfg.initial_mean_hole_radius_m
    th,a,metric=_hole_geometry(mean,cfg)
    base=_baseline_w(mean,cfg)
    pert=[]
    for t in th:
        pert.append(sum(A*math.cos(m*t+p) for m,A,p in zip(cfg.disturbance_modes,cfg.disturbance_amplitudes,cfg.disturbance_phases_rad)))
    dev=[2*b*p for b,p in zip(base,pert)]
    avg=math.fsum(dev)/len(dev); dev=[x-avg for x in dev]; dev[-1]-=math.fsum(dev)
    tmp=State(0,mean,0,dev,[0]*cfg.azimuthal_cells,0,0)
    *_,r,b=_geometry(tmp,cfg)
    u=[0.0]*cfg.azimuthal_cells
    for m,A,p in zip(cfg.disturbance_modes,cfg.disturbance_amplitudes,cfg.disturbance_phases_rad):
        omega=_rp_rate(cfg,m,mean,b)
        for i,t in enumerate(th): u[i]+= -2*mean*omega*A/m*math.sin(m*t+p)
    tmp.u=u
    return tmp

def _deriv(st,cfg):
    th,a,metric,w,r,mean=_geometry(st,cfg)
    hole_area=0.5*math.fsum(ai*ai for ai in a)*cfg.dtheta
    rim_mass=cfg.density_kg_m3*hole_area*cfg.film_thickness_m
    radial=st.radial_momentum/rim_mass
    perimeter=math.fsum(metric)*cfg.dtheta
    cap=2*cfg.surface_tension_n_m*perimeter
    visc=cfg.rim_drag_coefficient*cfg.dynamic_viscosity_pa_s*perimeter*radial
    dth=cfg.dtheta
    curvature=[]
    for i,ri in enumerate(r):
        im=(i-1)%len(r); ip=(i+1)%len(r)
        avg_metric=metric[i]
        second=(r[ip]-2*ri+r[im])/(dth*dth*avg_metric*avg_metric)
        curvature.append(1/ri-second)
    flux=[wi*ui/li for wi,ui,li in zip(w,st.u,metric)]
    dd=[]; ud=[]; nu=3*cfg.dynamic_viscosity_pa_s/cfg.density_kg_m3
    for i,ui in enumerate(st.u):
        im=(i-1)%len(r); ip=(i+1)%len(r); li=metric[i]
        fr=.5*(flux[i]+flux[ip]); fl=.5*(flux[im]+flux[i])
        dd.append(-(fr-fl)/dth)
        du=(st.u[ip]-st.u[im])/(2*dth*li)
        dk=(curvature[ip]-curvature[im])/(2*dth*li)
        d2=(st.u[ip]-2*ui+st.u[im])/(dth*dth*li*li)
        ud.append(-ui*du-(cfg.surface_tension_n_m/cfg.density_kg_m3)*dk+nu*d2)
    return radial,cap-visc,dd,ud,cap,visc

def _advance(st,cfg,dt):
    k1=_deriv(st,cfg)
    p=State(st.time_s+dt,st.mean_hole_radius_m+dt*k1[0],st.radial_momentum+dt*k1[1],
            [v+dt*d for v,d in zip(st.deviations,k1[2])],[v+dt*d for v,d in zip(st.u,k1[3])],st.cap_imp+dt*k1[4],st.visc_imp+dt*k1[5])
    k2=_deriv(p,cfg)
    return State(st.time_s+dt,st.mean_hole_radius_m+.5*dt*(k1[0]+k2[0]),st.radial_momentum+.5*dt*(k1[1]+k2[1]),
                 [v+.5*dt*(a+b) for v,a,b in zip(st.deviations,k1[2],k2[2])],[v+.5*dt*(a+b) for v,a,b in zip(st.u,k1[3],k2[3])],
                 st.cap_imp+.5*dt*(k1[4]+k2[4]),st.visc_imp+.5*dt*(k1[5]+k2[5]))

def _sample(st,cfg,initv):
    _,_,_,_,r,mean=_geometry(st,cfg); liq,_,_=_film_rim_volume(st,cfg)
    _,a,_=_hole_geometry(st.mean_hole_radius_m,cfg); area=.5*math.fsum(x*x for x in a)*cfg.dtheta; mass=cfg.density_kg_m3*area*cfg.film_thickness_m
    return Sample(st.time_s,st.mean_hole_radius_m,st.radial_momentum/mass,mean,min(r),max(r),(max(r)-min(r))/(2*mean),min(r)/mean,_mode_amps(r,cfg.disturbance_modes,cfg),abs(liq-initv)/initv)

def _interp_cross(left,right,attr,threshold,direction='up'):
    y0=getattr(left,attr); y1=getattr(right,attr)
    if y1==y0:return right.time_s
    f=(threshold-y0)/(y1-y0); return left.time_s+max(0,min(1,f))*(right.time_s-left.time_s)

def _neck_cells(r,cfg):
    mean=math.fsum(r)/len(r); out=[]
    for i,v in enumerate(r):
        if v<=r[(i-1)%len(r)] and v<r[(i+1)%len(r)] and v/mean<=cfg.partition_neck_radius_ratio:
            out.append(i)
    return tuple(sorted(out))

def _segment(start,end,n):
    out=[]; i=(start+1)%n
    while i!=end:
        out.append(i); i=(i+1)%n
        if len(out)>n: raise RuntimeError('segment traversal')
    return out

def _droplets(st,cfg,digest):
    th,a,metric,w,r,mean=_geometry(st,cfg); necks=_neck_cells(r,cfg)
    if len(necks)<2: raise RuntimeError('fewer than two evolved necks')
    _,aa,_=_hole_geometry(st.mean_hole_radius_m,cfg); area=.5*math.fsum(x*x for x in aa)*cfg.dtheta; massrim=cfg.density_kg_m3*area*cfg.film_thickness_m
    vr=st.radial_momentum/massrim; drops=[]
    for order,start in enumerate(necks):
        end=necks[(order+1)%len(necks)]; inds=_segment(start,end,cfg.azimuthal_cells)
        weighted=[(start,.5),*[(i,1.0) for i in inds],(end,.5)]
        vol=math.fsum(w[i]*cfg.dtheta*wt for i,wt in weighted); mass=cfg.density_kg_m3*vol
        cx=math.fsum(math.cos(th[i])*w[i]*wt for i,wt in weighted); cy=math.fsum(math.sin(th[i])*w[i]*wt for i,wt in weighted)
        ang=math.atan2(cy,cx)%TWO_PI; local_radius=st.mean_hole_radius_m*(1+cfg.hole_asymmetry_fraction*math.cos(cfg.hole_asymmetry_mode*ang))
        px=py=0.0
        for i,wt in weighted:
            cm=cfg.density_kg_m3*w[i]*cfg.dtheta*wt; u=st.u[i]; t=th[i]
            px+=cm*(vr*math.cos(t)-u*math.sin(t)); py+=cm*(vr*math.sin(t)+u*math.cos(t))
        suffix=hashlib.sha256(f'{digest}:{start}:{end}'.encode()).hexdigest()[:16]
        drops.append(Droplet(f'multimode-drop-{order:02d}-{suffix}',vol,mass,(3*vol/(4*math.pi))**(1/3),ang,(local_radius*math.cos(ang),local_radius*math.sin(ang)),(px/mass,py/mass),(px,py),start,end))
    return necks,tuple(drops)

def evolve_multimode_rim_breakup(cfg=None):
    cfg=cfg or MultimodeRimBreakupConfig(); st=_initial_state(cfg); initv=math.pi*cfg.outer_radius_m**2*cfg.film_thickness_m
    samples=[]; ligament=None; detach=None; prev=None
    while st.time_s<=cfg.max_time_s+0.5*cfg.time_step_s:
        sm=_sample(st,cfg,initv); samples.append(sm)
        if ligament is None and sm.total_amplitude_fraction>=cfg.ligament_amplitude_fraction:
            ligament=_interp_cross(prev,sm,'total_amplitude_fraction',cfg.ligament_amplitude_fraction) if prev else sm.time_s
        if ligament is not None and sm.neck_radius_ratio<=cfg.detachment_neck_radius_ratio:
            detach=_interp_cross(prev,sm,'neck_radius_ratio',cfg.detachment_neck_radius_ratio) if prev else sm.time_s; break
        if st.mean_hole_radius_m>=0.9*cfg.outer_radius_m: raise RuntimeError('film exhausted')
        if st.time_s>=cfg.max_time_s: raise RuntimeError('no detachment')
        prev=sm; st=_advance(st,cfg,min(cfg.time_step_s,cfg.max_time_s-st.time_s))
    if ligament is None or detach is None: raise RuntimeError('missing event')
    th,a,metric,w,r,mean=_geometry(st,cfg); init_modes=samples[0].mode_amplitudes; final_modes=_mode_amps(r,cfg.disturbance_modes,cfg)
    payload={'config':asdict(cfg),'detachment_time_s':float(detach).hex(),'mean_hole_radius_m':float(st.mean_hole_radius_m).hex(),'w':[float(x).hex() for x in w],'u':[float(x).hex() for x in st.u]}
    digest='sha256:'+hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    necks,drops=_droplets(st,cfg,digest); dropvol=math.fsum(d.volume_m3 for d in drops); _,film,rim=_film_rim_volume(st,cfg)
    verr=abs(film+dropvol-initv)/initv
    hole_area=.5*math.fsum(x*x for x in a)*cfg.dtheta; massrim=cfg.density_kg_m3*hole_area*cfg.film_thickness_m; vr=st.radial_momentum/massrim
    return Result(cfg,tuple(samples),ligament,detach,st.mean_hole_radius_m,vr,tuple(w),tuple(st.u),init_modes,final_modes,necks,drops,initv,film,rim,dropvol,verr,st.radial_momentum,st.cap_imp,st.visc_imp,st.radial_momentum-(st.cap_imp-st.visc_imp),digest,{
        'solver':'asymmetric-expanding-rim-multimode-slender-jet','version':'1.0.0','requirements':['R16','R31','R32','R33'],
        'hole_geometry':'SCALED_POLAR_MODE_ASYMMETRY','azimuthal_dynamics':'ONE_CONSERVATIVE_FINITE_VOLUME_STATE_WITH_SIMULTANEOUS_MODES',
        'ligament_selection':'EVOLVED_MULTIMODE_AMPLITUDE_AND_LOCAL_NECKS','detachment':'EVOLVED_GLOBAL_NECK_RATIO_THRESHOLD',
        'droplet_volume':'CONSERVATIVE_PARTITION_BETWEEN_EVOLVED_LOCAL_MINIMA','supported_class':'ONE_ASYMMETRIC_THIN_FILM_HOLE_SIMULTANEOUS_MULTIMODE_REDUCED_RIM',
        'unrestricted_3d_multi_hole_interaction':'UNSUPPORTED','singular_3d_ligament_pinchoff':'UNSUPPORTED','turbulent_atomization':'UNSUPPORTED','aerodynamic_secondary_breakup':'UNSUPPORTED','broad_spray_statistics':'UNSUPPORTED'})
