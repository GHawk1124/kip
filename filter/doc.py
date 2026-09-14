from kip import *
from pathlib import Path
import json
ROOT = Path.cwd()
reqs = Requirements.load("requirements.toml")
def asset(name, width=170, height=None):
    return Drawing(svg=(ROOT / "assets" / name).read_bytes(),width=width,height=height)

import sympy as sp


# %% text scope "Design intent" wrap_title=true
'A flat, directly contacting coarse / fine / coarse pack, captured between two annular frames and two identical machined cups. The outer orbital weld contains pressure; the coined frames and closed element seam prevent internal bypass. Service basis: water at 70 °F; 650 psi inside relative to atmosphere. Pressure ratings do not apply across a blocked screen. @src:user'


# %% draw cover "F100 / assembled isometric" caption="Build123d geometry, transparent VTK rendering. Ø82 mm body; 116 mm overall."
cover = asset('hero_embed.svg', 150, 95)


# %% table headline "Concept screening"
headline = Table(['Item', 'Result', 'Meaning'], [('Dry mass', '0.802 lb', 'Calculated; 20% growth still below 1 lb'), ('Clean Δp, nominal / surge', '0.48 / 3.83 psi', 'Conditional hydraulic hypotheses'), ('Housing at 1300 psi', '~199 MPa local elastic peak', 'Below 275 MPa yield; peak not converged'), ('99.9% at 3 µm', 'Not substantiated', 'Fine media selection is the first gate'), ('Crush / bypass seal', 'Development required', 'Geometry alone cannot certify sealing')])


# %% text coverdecision "Review position"
'This is a detailed development candidate, not a qualified pressure component. The strongest evidence is the mass model, exact seven-solid assembly, and elastic housing screening. No supplier has yet substantiated all retention, pressure-drop and dirt-capacity requirements for the selected fine-cloth envelope.'


# %% text requirements "01 / Requirements and interpretation" pagebreak=true
'This section lists what the filter must do and how each requirement is being checked.\n\nThe original pressure values were written as psid. The subsequent clarification governs: they are internal-to-external housing pressure differences, conventionally psig here. Pressure-drop limits are inlet-to-outlet differentials, reported in psi. The 5 psi clean limit is conservatively applied at both nominal and surge flow. The 18 psi loaded limit is evaluated at nominal flow, with surge also reported. Contaminant type and surge duration remain unspecified.'


# %% table req_matrix "Requirement-by-requirement assessment"
req_matrix = Table(['ID / requirement', 'Evaluation', 'Closure'], [('R01 / MEOP 650 psig', 'Elastic housing screen favorable', 'Qualified weld + leak/pressure test'), ('R02 / proof 1300 psig', 'Linear peak ~199 MPa; no test', 'Hydrostatic proof; no permanent set'), ('R03 / burst ≥2600 psig', 'Gross wall promising; local screen unresolved', 'Nonlinear analysis + destructive test'), ('R04 / 5 µm rating', '5-S geometric rating; GKD alternative', 'Define absolute criterion; particle challenge'), ('R05 / 99.9% at 3 µm', 'β3 ≥1000; no qualified catalog match', 'Lot and completed-assembly challenge'), ('R06 / 0.14 lbm/s', '3.818 L/min at 70 °F', 'Measured assembly flow curve'), ('R07 / surge 0.47 lbm/s', '12.817 L/min; duration unknown', 'Flow transient, shedding and retention'), ('R08 / clean Δp ≤5 psi', '0.48 nominal / 3.83 surge, assumed Cv,Ci', 'Supplier coefficients + clean-flow test'), ('R09 / dirt ≥0.318 g', 'Conditional on cake and contaminant', 'Specified retained dry dirt loading test'), ('R10 / loaded Δp ≤18 psi', '0.90 nominal for α=10^9 m/kg', 'Measured dirty-flow / efficiency curve'), ('R11 / mass ≤1 lb', '0.802 lb dry; 0.962 lb with 20% growth', 'Weigh actual dry finished filter'), ('R12 / water at 70 °F', '21.11 °C; fixed design temperature', 'Temperature-controlled qualification'), ('R13 / seven components', '7 CAD solids; 5-piece element', 'Drawing and assembly inspection')])


# %% text reqnotes "Remaining service definitions"
'Water chemistry, particle material/shape and size calibration, dirt feed concentration, lifetime throughput, pressure-cycle count, surge duration, allowable reverse flow, external line loads and installation line alloy require definition. These are open inputs, not silently satisfied requirements.'


# %% text architecture "02 / Architecture and material trade" pagebreak=true
'This section explains the seven parts and why each material was chosen.\n\nSelect commercially pure titanium Grade 2 for the two housing halves. Use annealed 316L sheet frames and a stainless fine/coarse pack. This hybrid arrangement avoids a titanium-to-stainless fusion joint: the internal pack is mechanically captured. The external stubs are integral titanium and assume compatible titanium lines. Stainless installation lines would require a separately engineered transition, outside this seven-part scope.'


# %% table bom "Seven-piece bill of materials"
bom = Table(['Part', 'Qty', 'Nominal definition'], [('F100-01 housing', '2', 'Identical CP Ti Grade 2 cups; integral ¾ in stubs'), ('F100-02 frame', '2', '316L annealed sheet; Ø70 / Ø58 × 0.200 mm blank'), ('F100-03 support', '2', '40 × 40, Ø0.254 mm wire; 0.480 mm calender target'), ('F100-04 fine cloth', '1', '5-S envelope, 0.180 mm; performance approval pending')])


# %% table materialtrade "Why titanium housing"
materialtrade = Table(['Option', 'Mass estimate', 'Decision'], [('Ti Grade 2 cups / SS element', '0.364 kg / 0.802 lb', 'Baseline; material and weld coupons required'), ('Same geometry, all 316L', '~0.631 kg / 1.392 lb', 'Fails 1 lb before growth'), ('All titanium media/frame', 'Not established', 'No sourced β3 or welding schedule')])


# %% text materialbasis "Material basis and interfaces"
'Use 275 MPa minimum yield and 345 MPa minimum tensile as room-temperature screening values for Grade 2, with 105 GPa elastic modulus and assumed Poisson ratio 0.34. Actual pressure-component stock must carry the applicable product-form certificate; cited catalog data do not certify an 82 mm machining blank. @src:timet @src:ati\n\nThe coarse catalog examples are T316, not certified 316L. The baseline drawing requires a certified 316L equivalent with the same construction and recalendered thickness, or a documented material change after weld development. Keep titanium and stainless fabrication tools segregated. Evaluate galvanic/crevice behavior for actual water chemistry.'


# %% text exploded "03 / Assembly and exploded views" pagebreak=true
'This section shows how the seven parts fit together.\n\nThe order is housing / frame / coarse / fine / coarse / frame / housing. The three mesh layers touch across the full active face. Both external frames are continuous annuli. All five element layers participate in the closed perimeter attachment.'


# %% draw exploded_fig "Seven components / separated axially" caption="Same CAD parts as the assembled model. Mesh discs are colored envelope solids, not pore-resolved woven wires."
exploded_fig = asset('exploded_render_embed.svg', 155, 140)


# %% text explodednotes "Reading the CAD"
'The STEP assembly contains seven valid, noninterfering solids. Fine and coarse discs are deliberately represented by their physical envelopes; treating those envelopes as solid plates in a structural or fluid solver would be incorrect. The colored render does not imply that water passes through solid CAD discs. Frames in the assembled model use a 0.170 mm coined envelope; the separate frame-blank STEP retains 0.200 mm stock thickness.'


# %% text geometry "04 / Housing geometry and orbital-weld rationale" pagebreak=true
'This section explains the housing shape and where its outer weld goes.\n\nThe axisymmetric cups combine an expanded element chamber with a conical transition to a straight tube stub. A cone carries pressure through membrane action more efficiently than a broad unsupported flat end cap, while providing a smooth flow transition and tool access. The small changes of slope are explicit sharp concept vertices; production blend radii remain a drawing-release task and must be included in the next stress model.'


# %% draw section_dim "Axial section A–A / dimensions in mm" caption="Dimensioned profile derived from design.py; symmetric halves about z=0. Section is schematic only in mesh porosity."
section_dim = asset('dimensioned_section.svg', 175, 110)


# %% text weldshape "Why the joining rim is circular"
'The Ø82 mm rim presents a constant-diameter circumferential square butt joint with a 2.50 mm radial fusion wall. Two identical ends permit repeatable concentric fixturing and a single orbital GTAW seam. The sealing land is at radius 32 mm; the independent closure stop is at radius 37–38 mm; a root relief separates the stop from the fusion wall at radius 38.5–41 mm. This prevents the element from being intentionally consumed in the housing weld.\n\nAn orbital head covering 82 mm diameter is available as a family, but its collet envelope and clearance over the short shoulder are not verified. Plan a fixture-specific open head or rotary welding station if a closed head cannot clear the cups. One seam may require multiple passes; “one weld” is not a promise of one pass. @src:orbital'


# %% text drawing_sheet "05 / CAD drawing sheet" pagebreak=true
'These drawings show the filter from the outside and sliced through the middle.\n\nBuild123d exports the solid assembly, exploded assembly, identical housing half and sheet blank as STEP. The center-plane section is also exported as a 1:1 millimeter DXF. Projection views below are actual OpenCascade visible/hidden-edge views, scaled to fit.'


# %% draw orthographic_sheet "Front, end, center section and housing half" caption="Section A-A is a true 2D intersection of the seven-part CAD assembly with the XZ plane at y=0. Mesh appears as thin envelopes; individual pores are not modeled. Views are scaled to fit."
orthographic_sheet = asset('orthographic_sheet.svg', 175, 170)


# %% text element "06 / Filter element and supplier definition" pagebreak=true
'This section shows the filter layers and identifies suppliers that could provide the mesh.\n\nThe fine-cloth baseline is a dimensional and hydraulic development candidate, not an approved β3 element. Haver’s specific 5-S construction provides traceable physical data; GKD provides a second traceable 5 µm weave family. The 3 µm efficiency requirement can force a finer custom cloth and a fresh hydraulic/stack calculation.'


# %% draw element_fig "Framed three-mesh pack / plan and stack" caption="Python/Matplotlib vector illustration: circles show the annular features and rectangles show the layers. The coarse mesh grid and exploded spacing are illustrative, not supplier-accurate weave geometry. Weld annulus Ø66–68, seal-track mean Ø64, trimmed OD Ø70; mesh remains intact across Ø58."
element_fig = asset('element_detail.svg', 170, 92)


# %% table suppliers "Traceable mesh sourcing"
suppliers = Table(['Supplier / item', 'Supported facts', 'Not established'], [('Haver / RPD HIFLO 5-S', '5 µm geometric pore; 0.18 mm', 'β3, Cv/Ci for water, exact alloy/lot'), ('GKD / 5 µm DTW family', '5 µm absolute-opening end of family', 'Exact SKU, thickness, β3, permeability'), ('TWP / 040X040T0100', '40 × 40; 0.254 wire; T316', '316L certificate; calendered performance'), ('Darby / 40316.010PL', 'Same coarse geometry; T316', '316L certificate; lot origin'), ('Dorstener / custom fabrication', 'Welding, laser trim, cleaning', 'Exact fine media and qualified seam')])


# %% text suppliercitations "Source trail"
'Fine-cloth references: @src:haver @src:gkd. Coarse cloth references: @src:twp @src:darby. Fabrication lead: @src:dwt. Require origin of the actual wire, weaving and processing if non-Chinese sourcing is retained; headquarters location is not origin evidence.'


# %% text retention "07 / Retention and the bypass budget" pagebreak=true
'This section explains how well the filter must catch particles and why water must not leak around the mesh.\n\nInterpret liquid efficiency as number-based capture at and above a defined 3 µm particle size: 99.9% corresponds to β3 ≥1000. A 5 µm geometric pore or “absolute opening” statement does not demonstrate that efficiency at 3 µm. No source located for this report verifies both requirements for a purchasable fine-cloth item. This is the principal open compliance issue.'


# %% symbolic beta_math "Efficiency relation"
N_up, N_down = sp.symbols("N_up N_down", positive=True)
beta_3 = N_up / N_down
eta_3 = 1 - 1 / beta_3


# %% text bypassbudget "Media plus assembly must meet the requirement"
'For a bypass flow fraction b carrying feed concentration, assembly efficiency is $eta_a = (1-b) eta_m$. If the cloth itself is only 99.9% efficient, essentially no bypass budget remains. A provisional allocation of 99.95% media efficiency and 0.05% maximum bypass gives 99.900025% assembly efficiency. That allocation is a design target, not a supplier claim.\n\nFor perspective, ideal radial slit flow across the Ø64 × 0.40 mm land follows $Q_b = pi h^3 Delta p / (6 mu ln(r_o/r_i))$. At 18 psi differential and nominal total flow, a uniform gap of about 2.29 µm already carries 0.1% bypass. A 0.05% budget reduces that ideal full-circumference gap to about 1.82 µm. Local scratches need their own length/width model; this calculation is sensitivity, not an allowable surface defect.'


# %% table retentiontests "Required evidence"
retentiontests = Table(['Test', 'Purpose'], [('Calibrated water particle challenge at 3 and 5 µm', 'Verify complete assembly efficiency, clean and loaded'), ('Pore characterization / wet integrity', 'Detect changed pores, damage or a gross bypass route'), ('Challenge after proof, surge and environmental exposure', 'Show retention survived manufacturing and loading'), ('Media coupons and closed-perimeter element coupons', 'Separate media, seam and housing-seat failure modes')])


# %% text retentionlimits "Test method selection"
'Particle counters, sampling volumes, background counts and particle-size calibration must be matched upstream and downstream. For ideal independent particles with zero downstream detections, approximately 2995 challenged particles give a one-sided 95% bound of 0.1% penetration; real flow sampling and counter uncertainty require a more complete protocol.\n\nISO 16889 is a useful multipass-method reference, but an adapted 70 °F water/3 µm test must not be called compliant without a scope review. ASTM F316 addresses membrane pore characterization and explicitly does not establish retention on its own. @src:iso @src:f316'


# %% text flow_basis "08 / Flow basis and clean-screen equation" pagebreak=true
'This section turns the required water flow into the speed of water through the filter.\n\nUse superficial approach velocity over the exposed Ø58 face, without dividing by porosity again. Body loss is evaluated separately using the Ø15.75 bore velocity. Water properties are approximate ambient-pressure values at 70 °F; pressure dependence is omitted in this screening calculation. @src:water'


# %% given fluidinputs "Water and geometry"
rho_w = 997.99 * kg / m**3
mu_w = 0.000979 * Pa * s
d_face = 58 * mm
d_bore = 15.75 * mm
mdot_n = 0.14 * lb / s
mdot_s = 0.47 * lb / s


# %% calc approach "Exposed area and approach velocity" unit="A_face=mm**2, U_n=m/s, U_s=m/s"
A_face = pi * d_face**2 / 4
U_n = mdot_n / (rho_w * A_face)
U_s = mdot_s / (rho_w * A_face)


# %% symbolic flowmodel "Screen-specific resistance model"
Cv, Ci, visc, dens, velocity = sp.symbols("C_v C_i mu rho U", positive=True)
dp_screen = Cv * visc * velocity + Ci * dens * velocity**2


# %% text equationscope "Use of the supplied equations"
'Here $C_v = A_1 L / D_a^2$ and $C_i = A_2 L / D_a$. Their units are inverse meters and dimensionless respectively. The fitted approach preserves the user-supplied Eq. 2-2 in coherent SI; the force conversion constant is unity and is not gravitational acceleration. Never substitute a 5 µm filtration rating for average capillary diameter. @src:user\n\nThe user-transcribed 200 × 1400 example gives about 5.38 × 10^7 /m and 116.3; those coefficients belong to that tested cloth, not to HIFLO 5-S or an arbitrary finer Dutch weave. The original NASA report file/identifier is not available here, so the transcription is not independently certified.'


# %% text hydraulics "09 / Hydraulic sizing and surge margin" pagebreak=true
'This section estimates how much pressure the clean filter uses at normal and surge flow.\n\nUse the same equation for each screen in series. A deliberately explicit baseline hypothesis for the fine layer is $C_v = 6 times 10^7$ /m and $C_i = 3000$. The pair of coarse supports adds 2 × 10^5 /m and 40. A total stub/transition coefficient K=3 is applied to bore velocity. These are sensitivity inputs, not fitted supplier coefficients.'


# %% draw hydraulic_fig "Resistance envelope" caption="Only Cv varies in these curves; Ci=3000 and K=3 remain fixed. 70 °F water."
hydraulic_fig = asset('hydraulics.svg', 165, 65)


# %% given hyd_inputs "Hydraulic hypotheses"
C_vf = 6e7 / m
C_if = 3000
C_vc = 2e5 / m
C_ic = 40
K_body = 3


# %% calc hyd_surge "Surge assembly pressure drop" unit="A_bore=mm**2, V_bore=m/s, DP_s=psi"
A_bore = pi * d_bore**2 / 4
V_bore = mdot_s / (rho_w * A_bore)
DP_s = (C_vf + C_vc) * mu_w * U_s + (C_if + C_ic) * rho_w * U_s**2 + K_body * rho_w * V_bore**2 / 2


# %% text hyd_conclusion "What the estimate supports"
'The baseline predicts 0.48 psi nominal and 3.83 psi surge, leaving 1.17 psi surge margin to the 5 psi limit. At these coefficients the fine-layer inertial term dominates surge. The smaller preliminary Ø42 disc and ½ inch stubs did not provide this margin. The inlet jet may produce nonuniform face loading; K does not model that distribution. An assembled flow test or porous-media CFD should assess effective area.\n\nHaver publishes a pressure-drop coefficient of 9020, but its tabulated value lacks the water/velocity convention needed to fit both coefficients here. If one hypothetically interprets it as Δp=9020 ρU²/2, then Ci=4510 and the predicted surge drop is about 5.26 psi. That interpretation is not adopted as validated data; it illustrates why obtaining the actual curve is a mandatory gate. @src:haver'


# %% text correlation "10 / Fit strategy and Armour–Cannon cross-check" pagebreak=true
'This section explains how real mesh measurements will replace the current flow estimates.\n\nObtain at least five mesh-only pressure-drop points covering nominal through surge velocity at 70 °F, with a zero-flow offset check and an empty-holder subtraction. Record exposed area, pressure taps, actual thickness, alloy/heat, weave, calender condition and test-fluid properties.'


# %% text fit_formula "Fit the supplied model"
'The linearized relation is $Delta p/(mu U) = C_v + C_i (rho U/mu)$. Use nonnegative least squares, check residuals and confidence bounds, and independently validate at another flow or sample. The delivered fit_mesh.py fits the equivalent untransformed pressure equation with scaled columns to avoid numerical conditioning issues. It requires a real CSV; this project contains no synthetic file presented as supplier data.\n\nThe transformation makes errors heteroscedastic near zero velocity. Weight by measurement uncertainty or fit the untransformed equation directly. If the tested range cannot identify both coefficients, report that limitation instead of treating an uncertain inertia term as zero.'


# %% text AC "Geometry-based cross-check"
'With matched definitions, the supplied Armour–Cannon relation is:\n\n$ Delta p = (tau L)/(epsilon^2) (8.61 mu a^2 U + 0.52 rho U^2 / D_B) $\n\nHIFLO’s catalog thickness and mass give a useful consistency check: 1 − 0.95/(8000 × 0.00018) ≈ 0.340 volumetric porosity. However, actual wire surface area per volume a, the applicable bubble-point diameter and a justified tortuosity are missing. HIFLO is not conventional Dutch twill; assigning the Dutch-weave tortuosity 1.30 to it is an unvalidated transfer. Accordingly no fabricated Armour–Cannon prediction is substituted for a measured curve. @src:armour @src:haver\n\nThe report-wide fit f=2.49/Re+0.30 and the straight-capillary Poiseuille model are not used for baseline prediction. The supplied research warns of aggregate correlation scatter and rejects the capillary model for predicting Dutch-twill resistance. @src:user'


# %% text fit_code "Simplified fitting code"
'```python\nU = mdot / (rho * exposed_area)\nX = column_stack([mu * U, rho * U**2])\nscale = norm(X, axis=0)\ncoef, residual = nnls(X / scale, measured_mesh_dp)\nCv, Ci = coef / scale\n```\nThe fit coefficients belong to the tested finished material. Refit after a media change or a process that alters its hydraulic structure.'


# %% text dirt "11 / Retained dirt and loaded pressure drop" pagebreak=true
'This section estimates how collected dirt makes water harder to push through the filter.\n\nInterpret containment capacity as at least 0.318 g of retained dry particulate mass before the nominal-flow assembly drop reaches 18 psi. It is not feed mass, deposited wet mass or geometric void volume. The contaminant is still unspecified, so this requirement remains unverified.'


# %% draw dirt_fig "Cake resistance sensitivity" caption="No blockage penalty is added to the same cake; 70 °F water, 0.318 g retained dirt."
dirt_fig = asset('dirt.svg', 170, 85)


# %% text cakemodel "Use the supplied series-cake equation"
'$ Delta p_l = C_v mu U + C_i rho U^2 + mu U alpha_c m_d / A_f $\n\nAt α=10^9 m/kg, calculated assembly drop is 0.90 psi nominal and 5.21 psi surge. The 18 psi nominal limit permits α up to approximately 4.26e+10 m/kg under the baseline clean assumptions. That is a required contaminant-performance envelope, not a measured dirt capacity. At α=10^11 m/kg the nominal loaded drop is over 40 psi, so the same mass fails.\n\nThe alternative blocked-area model replaces U by U/F. It reaches 18 psi nominal at about 87.5% completely blocked face under the baseline coefficients. That percentage cannot be converted into grams without a deposit model. Do not add blockage and cake penalties for the same dirt. Feed concentration and size-dependent capture are also required to convert retained mass into service life.'


# %% text pressure "12 / Housing pressure screening" pagebreak=true
'This section checks whether the housing can hold the required water pressure.\n\nThe equal-pressure housing case applies water pressure to both cavities with atmospheric pressure outside. It includes closed-end thrust transferred through the integral tube stubs. The 18 psi element drop is a separate small imbalance; 650/1300/2600 psi are not applied across the screen. No fatigue life, weld flaw tolerance or external piping loads are established.'


# %% given pressinput "Pressure and weld-rim section"
p_meop = 650 * psi
p_proof = 1300 * psi
p_burst = 2600 * psi
r_i = 38.5 * mm
r_o = 41 * mm
S_y = 275 * MPa
S_u = 345 * MPa


# %% calc lame "Closed-end thick-cylinder check at the weld rim" unit=MPa
sigma_h = p_burst * (r_o**2 + r_i**2) / (r_o**2 - r_i**2)
sigma_z = p_burst * r_i**2 / (r_o**2 - r_i**2)
sigma_r = -p_burst
sigma_vm = (((sigma_h-sigma_z)**2 + (sigma_z-sigma_r)**2 + (sigma_r-sigma_h)**2) / 2)**0.5


# %% text stressmeaning "Interpretation"
'This treats the 2.50 mm fusion wall as fully effective Grade 2 material and checks a local cylindrical section. It does not represent the conical transition, weld residual stress, incomplete penetration or a burst failure model. A 10% loss of effective fusion thickness raises membrane stress by roughly 11%; the minimum weld wall must be measured on development sections.\n\nUse a hydrostatic proof criterion of no leakage and no unacceptable permanent deformation, followed by internal integrity checks. Burst acceptance requires survival to at least 2600 psig without pressure-boundary rupture under a defined ramp. The qualification plan must define hold times, ramp rates, cycles and destructive-sample count; they are not specified by the supplied requirements.'


# %% text fem "13 / Axisymmetric hydrostatic simulation" pagebreak=true
'This section uses a computer model to estimate housing stress and movement under pressure.\n\nA custom linear-elastic axisymmetric finite-element solver uses three-node triangles with three integration points and full hoop strain N/r. It meshes the same radial profile used by Build123d. Titanium is homogeneous and isotropic. The welded rim and stop plane receive axial symmetry constraints. Pressure is applied to exposed internal faces; the seal contact track is omitted from fluid traction. There is no explicit gasket/contact preload.'


# %% draw fem_fig "650 psig / transparent pressure-stress rendering" caption="Upper half only, 270-degree sweep. Undeformed geometry. MPa scale; PyVista/VTK render of the supplied ParaView-readable VTU field."
fem_fig = asset('pressure_render_embed.svg', 155, 113)


# %% table fem_mesh "Mesh sensitivity / 650 psi"
fem_mesh = Table(['Target h (mm)', 'Triangles', 'Peak VM (MPa)', 'Seat opening (µm)'], [('1.2', '529', '64.1', '3.72'), ('0.7', '1384', '86.1', '3.46'), ('0.4', '3914', '99.7', '3.40')])


# %% text femvalidation "Validation and limits"
'A separate closed-end thick-cylinder benchmark agrees with the Lamé stress field to 2.30% in an interior region. The finest mesh balances axial load and reaction to numerical precision. Smooth cone stress changes about 0.6% between the last two meshes. Sharp-corner peak stress rises with refinement and is not converged. The finest elastic peak is 99.7 MPa at MEOP, 199.4 MPa at proof, and 398.7 MPa by linear extrapolation to burst. The burst extrapolation exceeds minimum tensile strength locally and is not a prediction of physical rupture. Resolve fillets, contact, weld geometry and elastoplastic response before claiming pressure compliance.'


# %% text seal_geometry "14 / Crush seal and tolerance detail" pagebreak=true
'This section shows where the housing squeezes the metal frames to stop water going around the mesh.\n\nHousing lands bear on solid annular sheet surfaces at Ø64. The resistance seam is outside that contact track at Ø66–68. The outermost millimeter of frame radius remains between the seam and trimmed Ø70 edge. The contact track must stay free of weld depressions, scratches and laser debris.'


# %% draw seal_fig "Detail B / frame contact, independent stop, weld rim" caption="CAD resolves the radial placement and separate stops. Axial scale is enlarged; dimensions govern."
seal_fig = asset('seal_detail.svg', 175, 95)


# %% table tolerance_definition "Provisional manufacturing controls"
tolerance_definition = Table(['Feature', 'Nominal / tolerance', 'Purpose'], [('Finished element T at seal track', '1.540 ±0.006 mm', 'Gauged AFTER resistance welding'), ('Selective assembly gate', 'T − hA − hB = 0.060–0.065 mm', 'Measured pair accepted before final closure'), ('Each land height from datum A', '0.740 ±0.003 mm', 'Two halves give 1.480 ±0.006 gap'), ('Combined face form contribution', '±0.004 mm total allowance', 'Flatness / parallelism budget'), ('Land mean diameter / width', 'Ø64 / 0.400 ±0.030 mm', 'Solid-frame contact region'), ('Frame ID / final OD', 'Ø58 ±0.10 / Ø70 ±0.05 mm', 'Active area / edge capture'), ('Pocket diameter', 'Ø70.40 +0.05/−0.00 mm', '0.175 mm minimum radial clearance'), ('Independent stop / weld relief', 'r37–38 / r38–38.5 × 0.15 deep', 'Stop outside element; root isolation'), ('Surface targets', 'Land Ra ≤0.4 µm; no radial scratches', 'Provisional finish; test must validate')])


# %% text seal_stack "15 / Tolerance stack and residual contact" pagebreak=true
'This section checks how small size differences affect the squeeze on the seal.\n\nDefine geometric closure before pressurization as $delta = T - h_A - h_B + e_f + s_w - r$. Here e_f is combined form error, s_w is net axial weld closure and r represents settlement/recovery. The nominal pre-weld overlap is 60 µm. This is not the elastic compression remaining after coining.'


# %% table stack_values "Worst-case arithmetic / micrometers"
stack_values = Table(['Contribution', 'Range', 'Basis'], [('Nominal T − hA − hB', '60', '1.540 − 0.740 − 0.740 mm'), ('Element thickness deviation', '−6 to +6', 'Finished annulus measured, not raw cloth sum'), ('Two land heights', '−6 to +6', '±3 µm per half'), ('Combined face form', '−4 to +4', 'Explicit provisional budget'), ('Weld closure', '0 to +12', 'Assumed development envelope'), ('Settlement / recovery', '−8 to 0', 'Assumed development envelope'), ('MEOP opening', '−3.40', 'Equal-pressure elastic model; no preload'), ('Residual geometric overlap', '32.6 to 84.6', 'Worst-case sum; target 40–90 not guaranteed')])


# %% text contactwarning "Crush is not proof of preload"
'A coined metal washer loses most of its plastic deformation as usable elastic travel. It can retain positive geometric overlap yet lose contact force after housing distortion. The unloaded-to-MEOP model predicts about 3.40 µm increase in land gap; proof doubles that elastic estimate. The completed assembly therefore needs a nonlinear contact/coining model correlated with measured load–closure curves, springback and pressure-driven opening. The finite-element opening is only a sensitivity term because the present solver omits preload and stop contact separation.\n\nA 0.40 mm land has about 80.4 mm² projected annular contact area per face. An assumed 250–450 MPa local coining pressure corresponds to 20–36 kN axial fixture force (not twice that force for two faces). These pressures can plastically deform Grade 2 lands as well as 316L sheets; they are not a released assembly force. Develop sheet hardness, land shape and closure together. Control on closure, force signature and coupon evidence, not force alone.'


# %% text stackclosure "How to close the tolerance requirement"
'Adopt a selective assembly gate: measured T − hA − hB must be 60–65 µm before applying the other allowances. With the same form, weld and recovery bounds, residual geometric overlap is 44.6–77.6 µm at MEOP and 41.2–74.2 µm at proof. Both fit the provisional 40–90 µm geometric window. This closes the arithmetic only if the assumed process bounds hold; it does not establish residual contact pressure.\n\nGauge the finished perimeter at multiple azimuths and clock the halves to measured face maps. Match measured element thickness to finished land heights; reject or rematch combinations outside 60–65 µm. Measure weld shrinkage and residual preload on representative coupons. Repeat internal particle/bypass verification after proof and relevant thermal/vibration exposure. An external helium test establishes housing leakage only; it does not prove this seal or the fine-mesh perimeter.'


# %% text monte "16 / Monte Carlo / what the unknowns change" pagebreak=true
'This section tries many possible input values to show which unknowns matter most.\n\n100,000 seeded independent draws explore assumed ranges, not measured production distributions. Cv is log-uniform from 2×10^7 to 2×10^8 /m; Ci from 300 to 10,000; cake resistance from 10^8 to 10^11 m/kg. K is uniform 1.5–6; active diameter 57.9–58.1 mm. Temperature is fixed at the required 70 °F. Tolerance terms use the bounded ranges on the previous page, including the calculated MEOP opening.'


# %% draw mc_fig "Hydraulic and geometric sensitivity" caption="Seed 6501300. Independent analyst assumptions; these fractions are not probabilities of field success."
mc_fig = asset('monte_carlo.svg', 175, 83)


# %% table mc_results "Fraction of assumed samples meeting a screen"
mc_results = Table(['Screen', 'Fraction', 'Interpretation'], [('Clean nominal ≤5 psi', '100.00%', 'Nominal flow is relatively forgiving'), ('Clean surge ≤5 psi', '73.08%', 'Fine-cloth inertia/resistance is critical'), ('Loaded nominal ≤18 psi', '87.70%', 'Depends strongly on contaminant α'), ('Both hydraulic limits', '64.17%', 'No supplier or assembly evidence included'), ('Geometric overlap 40–90 µm', '99.928%', 'Does not assess leakage or contact pressure'), ('Selective pairing yield', '36.78%', 'Randomly paired candidates within 60–65 µm')])


# %% text mcinterpretation "Decision use"
'Retention, actual weld defects, land damage and fatigue are not sampled. The priors are arbitrary engineering exploration bounds; different bounds and correlations change the fractions. A high geometric fraction cannot override the failing unsorted stack or prove a sealed joint. The 60–65 µm selective assembly gate removes the dimensional outliers under these assumed process bounds; it does not remove contact-model uncertainty. The next most valuable information is a β3-qualified fine cloth with a measured water curve, followed by seal/coining coupons. Simulation effort should narrow those uncertainties before expanding model complexity.'


# %% text mesh_strength "17 / Element support and dirt loading mechanics" pagebreak=true
'This section checks how the coarse mesh supports the fine mesh when water pushes on it.\n\nAt the 18 psi loaded-flow limit, the Ø58 active region carries about 328 N net axial load. One downstream coarse cloth is the primary support; the upstream cloth protects the fine layer and can react reverse loading. Direct mesh contact minimizes unsupported fine-cloth spans, but does not turn three woven layers into a bonded plate.'


# %% text supportcalc "Screening the support load path"
'For 40 mesh/in and 0.254 mm wire, pitch is 0.635 mm. The two orthogonal wire families have an equivalent metal line area $t_e = 2(pi d_w^2/4)/s approx 0.160$ mm. Using 170 MPa only as a reference solid-sheet yield stress gives about 27.1 N/mm line tension. A full-circumference upper-bound axial capacity with sin(slope)=1 is approximately 4.94 kN. This is an optimistic strength bound, not a support qualification: real slopes, anisotropy, wire crimp, boundary capture and local fine-wire bending govern. @src:ss\n\nA taut-membrane scale estimate using $w approx (3 p a^4 / (8 E t_e))^(1/3)$ gives roughly 1–2 mm deflection at 18 psi for effective modulus 193–30 GPa. That is consistent with needing millimeter-scale cavity clearance, not an assumption of a rigid flat disc. The opening-side cavity has 4.5 mm nominal shoulder height. This estimate is not a predictive woven-cloth constitutive model, and the existing envelope CAD is not a structural mesh model.'


# %% text supportverify "Verification needed"
'Pressure-cycle a completed element to at least the required operating differential, including the measured dirty surge transient; inspect permanent set, shedding and retention. If support fails, a housing-integral support pattern can preserve the seven-piece count, but it reduces accessible area and changes hydraulics. No such backing grid is included or credited in this baseline.\n\nFor the nominal 1 mm resistance-seam band at mean radius 33.5 mm, average axial shear from 328 N is about 1.56 MPa. That low average does not prove closed pores, peel resistance, uniform nugget overlap or resistance to wire pullout. Fine-layer edge bypass remains a functional-test requirement.'


# %% text thermal "18 / Orbital weld, thermal separation and fit-up" pagebreak=true
'This section explains how to weld the housing and protect the filter from weld heat.\n\nThe element plane and orbital seam are both centered at z=0 because the cups are identical and opposed. There is zero axial separation. The nearest nominal fusion root is radius 38.5 mm; the frame OD is radius 35 mm, giving 3.5 mm radial separation. An annular moat at radius 35.2–37 mm, 2 mm deep per half, interrupts direct conduction near the frame. This is an explicit development departure from the research’s requested axial thermal offset.'


# %% draw cutaway_fig "Housing and pack / cutaway isometric" caption="Rendered CAD cutaway. Radial thermal relief is visible outside the captured element."
cutaway_fig = asset('cutaway_embed.svg', 145, 100)


# %% text thermalcalc "Why radial spacing is not yet sufficient evidence"
'Using titanium k≈21.8 W/(m K), density 4510 kg/m³ and assumed heat capacity 520 J/(kg K), the diffusion length $sqrt(alpha t)$ is about 9.6 mm over 10 s, already larger than the radial clearance. This scale estimate is not a transient temperature prediction. Weld heat input, travel speed, fixture heat sinking, radiation and contact conductance are missing. @src:timet\n\nUse full weld/HAZ inert shielding, including the internal purge and trailing protection. Monitor purge quality and oxygen pickup through qualified process controls. Keep weld heat, crater closure and start/stop overlap away from a presumed single acceptable temperature criterion; establish acceptance using instrumented coupons, metallography and mechanical/cleanliness checks. @src:weld\n\nProvisional fit-up targets: weld-end squareness within 0.03 mm, radial mismatch ≤0.05 mm, and root gap 0–0.05 mm while the hard stop is engaged. These are development targets requiring WPS confirmation. Provide accessible fixturing faces without clamping on the fragile element.'


# %% text manufacturing "19 / Manufacturing process plan" pagebreak=true
'This section gives the steps for making, assembling and inspecting the filter.\n\nMake the element in a clean stainless fabrication stream, then assemble it into separately prepared titanium housings. Precut the washer ID before placing it on the mesh. Never laser-cut the central opening through the assembled five-layer pack.'


# %% table operations "Traveler / development sequence"
operations = Table(['Step', 'Operation', 'Record / acceptance evidence'], [('10', 'Receive certified alloy stock and cloth', 'Heat/lot, weave, origin, thickness and material certificate'), ('20', 'Machine one housing design twice', 'Datum A stop; bore axis B; seat/land map; minimum wall'), ('30', 'Prepare annular 316L blanks', 'Ø58 ID first; stock OD for later trim; deburr/clean'), ('40', 'Calender and stack coarse/fine/coarse', '0.480 mm coarse target; fine weave remains intact'), ('50', 'Resistance-weld closed annulus', 'Through all five layers; schedule, current, force, overlap'), ('60', 'Trim only final outer outline', 'Ø70 OD outside closed band; ≥1 mm nominal edge capture'), ('70', 'Clean and inspect element', 'Debris, recast, loose wires, pore integrity and flow'), ('80', 'Gauge finished seal track', 'T=1.540±0.006 mm AFTER seam; inspect multiple azimuths'), ('90', 'Select pair; fixture closure / coin', '60–65 µm measured overlap; force–closure and face maps'), ('100', 'Orbital-weld housing to housing', 'Qualified full-penetration titanium seam and purge'), ('110', 'Final clean and pressure verification', 'Proof, external leak, internal retention and shedding'), ('120', 'Mark and package', 'Traceable serial/lot; protected weld stubs; cleanliness record')])


# %% text processdevelopment "Parameters that remain experimental"
'Electrode material/shape, number of passes, nugget pitch, welding current, force and time need development on the actual five-layer stack. Use a continuous seam or qualified overlapping nuggets that leave no circumferential bypass route. Scattered retention spots or separate frame-to-coarse welds are insufficient evidence. A resistance-welded annulus can still contain connected pore paths; sectioning and functional challenge are required.\n\nDo not translate solid-sheet weld settings directly to woven cloth. Inspect after element fabrication and again after housing welding. Passivation/cleaning of stainless must be compatible with the fine media; cleaning of the hybrid final assembly must also be qualified for titanium.'


# %% text qualification "20 / Qualification and release gates" pagebreak=true
'This section lists the tests and evidence still needed before the filter can be used.\n\nThe design is ready for supplier discussion, tooling feasibility and coupon development. It is not ready for fabrication as a flight/service-qualified filter. No test certificates, supplier quotations or accepted weld procedures are included.'


# %% table gates "Evidence required before release"
gates = Table(['Gate', 'Pass evidence', 'Current disposition'], [('G1 / media selection', 'β3 ≥1000 and defined 5 µm retention; actual Cv/Ci', 'OPEN; possible finer media needed'), ('G2 / closed element perimeter', 'Microscopy/sections plus bypass and shedding tests', 'OPEN; five-layer seam unqualified'), ('G3 / frame/housing sealing', 'Contact/coining validation; pressure and exposure tests', 'OPEN; dimensions alone insufficient'), ('G4 / housing pressure boundary', 'WPS/PQR, NDE, proof and burst qualification', 'OPEN; elastic screening only'), ('G5 / flow and capacity', '≤5 psi clean and ≥0.318 g at ≤18 psi', 'OPEN; dust and real media curve missing'), ('G6 / mass and installation', '≤1 lb finished; compatible line alloy and weld access', 'CALCULATED mass; fit-up to confirm')])


# %% text test_sequence "Recommended test sequence"
'First characterize media coupons and full closed-seam elements. Next develop coining and housing-weld coupons with instrumented temperature and closure measurements. On completed assemblies, establish clean flow and particle retention before proof, then repeat internal integrity after proof. Run nominal and surge flow during controlled dirt loading; record retained dry mass, pressure drop, particle penetration and shedding. Use separate qualified samples for destructive burst so a destroyed item is never mistaken for a deliverable.\n\nSelect sample counts and confidence targets with the qualification authority. Hold times, leakage acceptance, allowable permanent set and environmental spectra require explicit approval in the eventual test procedure. External helium leakage and internal filtration integrity are separate acceptance lines.\n\nIf axial element-to-fusion offset becomes mandatory, revise the identical-half architecture rather than relabel radial clearance as axial separation. If stainless installation lines are mandatory, revisit material selection or allocate a qualified transition outside the seven-part filter definition.'


# %% text repro "21 / Reproducibility and simplified simulation code" pagebreak=true
'This section explains how to rerun the code and recreate the drawings and calculations.\n\nAll project code and generated outputs reside under filter/. Kip source code is unchanged. The local uv environment is locked; build123d is the requested CAD library. Full calculations, seeds, meshes, pressure fields, STEP files and rendered views are included.'


# %% text runcommands "Build sequence"
'```text\nuv sync\nuv run python cad_model.py\nuv run python hydrostatic_fem.py\nuv run python analysis.py\nuv run python figures.py\nuv run python author_document.py\nuv run kip check\nuv run kip build --output F100_engineering_design.pdf\n```\nThe requirements check intentionally leaves untested service requirements unverified. A successful document build is not engineering qualification.'


# %% text femcode "Simplified axisymmetric finite-element assembly"
'```python\n# Strains: radial, axial, hoop, engineering shear.\nB[0, 0::2] = dN_dr\nB[1, 1::2] = dN_dz\nB[2, 0::2] = N / radius\nB[3, 0::2] = dN_dz\nB[3, 1::2] = dN_dr\nKe += B.T @ D @ B * (2*pi*radius*area/3)\nK = assemble_sparse(element_matrices)\nu[free] = spsolve(K[free][:,free], load[free])\nstress = D @ B @ element_displacement\n```\nFull code includes three-point area integration, consistent pressure traction, closed-end thrust, boundary conditions, reaction balance, a Lamé benchmark and three mesh densities.'


# %% text paraview "ParaView deliverable"
'Open output/analysis/housing_pressure_650psi.vtu in ParaView and color by cell von_Mises_MPa. The delivered transparent PNG was produced with PyVista/VTK, not a running ParaView application. paraview_render.py reproduces a true ParaView transparent screenshot with pvpython when that application is installed. No background, ground plane or decorative geometry is included in the stress render.\n\nThe .vtu file is a swept axisymmetric result, not an independent three-dimensional solution. Housing stress does not include filter preload or model the woven cloth; the field must not be reused as evidence for element strength or sealing.'


# %% text mass_verification "22 / Auditable calculations and verification record" pagebreak=true
'This section shows how the filter weight was calculated and checked.\n\nThe mass estimate uses actual housing CAD volume, solid blank-frame mass and catalog areal weights for the mesh envelopes. Solid-disc envelope volumes are not used as mesh metal mass. Coarse mass is based on the raw construction; calendering does not remove metal.'


# %% given mass_inputs "CAD volume and areal masses"
V_half = 38331.113210503 * mm**3
rho_ti = 4510 * kg / m**3
m_frames = 0.003860389053 * kg
m_coarse = 0.010522278773 * kg
m_fine = 0.003656028451 * kg
growth = 1.20


# %% calc mass_calc "Dry finished mass with a development reserve" unit="m_dry=lb, m_reserve=lb"
m_dry = 2 * V_half * rho_ti + m_frames + m_coarse + m_fine
m_reserve = growth * m_dry
MS_mass = (1 * lb) / m_reserve - 1


# %% text mass_scope "Mass scope"
'This is dry hardware mass including both integral stubs, before any additional mounting hardware, line transitions or external piping. The 20% multiplier is a design reserve, not a Monte Carlo tolerance prediction. Trapped water mass is excluded because the requirement has been interpreted as dry component mass. The estimate leaves only about 0.038 lb after that reserve; a substantial new support or transition must trigger reweighing.'


# %% text ledger_intro "23 / Verification ledger" pagebreak=true
'This section separates requirements already checked from those still waiting for evidence.\n\nOnly mass by analysis and the seven-component count have supporting verification entries. The remaining service requirements deliberately stay OPEN until the evidence identified in the release gates exists. This ledger distinguishes successful calculation execution from qualification of manufactured hardware.'


# %% table formal_checks "Kip requirement ledger"
reqs.verify("R11", m_reserve, "<= 1 * lb", evidence="mass_calc")
reqs.verify("R13", 7, "== 7", evidence="Seven valid noninterfering CAD solids; cad_model.py")
ledger = compliance_matrix(reqs)


# %% text references_intro "24 / References and source limitations" pagebreak=true
'This section lists the sources used and explains what they do and do not prove.\n\nSupplier references establish specific catalog facts and sourcing leads, not quotations or certificates for delivered material. All online sources were checked on 2026-09-14. Analysis inputs not attributed to a supplier are explicitly engineering hypotheses. The user-supplied research is retained as the authority for the architecture and selected hydraulic equations.'


# %% sources references "Traceable references"
refs = Sources(**{key: Source(**value) for key, value in json.loads((ROOT / "sources.json").read_text(encoding="utf-8")).items()})
