
# Extended version: Also returns list of dictionaries

from typing import Union, List

class Tech:
    def __init__(self, name: str, id: Union[str, int], leads_to: List[Union[str, int]]):
        self.name = name
        self.id = id
        self.leads_to = leads_to

    def __repr__(self):
        return f"Tech(name={self.name!r}, id={self.id!r}, leads_to={self.leads_to!r})"


# Full tech data block (still truncated for demo)
full_raw_data = """
Technology 	Prerequisites 	Leads to 	Track and level 
   Adaptive Doctrine (Alien Crossfire only) 	Polymorphic Software Doctrine: Flexibility 	Advanced Military Algorithms 	Conquer 3 
   Adaptive Economics (Alien Crossfire only) 	Progenitor Psych Industrial Economics 	Planetary Economics 	Build 3 
   Advanced Ecological Engineering 	Fusion Power Environmental Economics 	Centauri Psi 	Build 7 
   Advanced Military Algorithms 	Adaptive Doctrine (Alien Crossfire only) Doctrine: Flexibility (Vanilla only) Optical Computers 	Pre-Sentient Algorithms Retroviral Engineering 	Conquer 4 
   Advanced Spaceflight 	Orbital Spaceflight Organic Superlubricant 	Super Tensile Solids 	Discover 8 
   Advanced Subatomic Theory 	High Energy Chemistry Polymorphic Software 	Applied Relativity Silksteel Alloys 	Discover 3 
   Applied Gravitonics 	Graviton Theory Digital Sentience 	Controlled Singularity 	Explore 14 
   Applied Physics 		Nonlinear Mathematics High Energy Chemistry Optical Computers 	Conquer 1 
   Applied Relativity 	Superconductor Advanced Subatomic Theory 	Unified Field Theory Photon/Wave Mechanics 	Discover 5 
   Bio-Engineering 	Gene Splicing Neural Grafting 	Retroviral Engineering 	Build 5 
   Bioadaptive Resonance (Alien Crossfire only) 	Field Modulation Centauri Empathy 	Sentient Resonance 	Conquer 4 
   Biogenetics 		Secrets of the Human Brain Gene Splicing 	Discover 1 
   Biomachinery 	Mind/Machine Interface Retroviral Engineering 	Homo Superior N-Space Compression 	Build 7 
   Centauri Ecology 		Centauri Empathy Ecological Engineering Field Modulation 	Explore 1 
   Centauri Empathy 	Secrets of the Human Brain Centauri Ecology 	Centauri Meditation Bioadaptive Resonance 	Explore 3 
   Centauri Genetics 	Centauri Meditation Retroviral Engineering 	Centauri Psi 	Explore 7 
   Centauri Meditation 	Ecological Engineering Centauri Empathy 	Centauri Genetics 	Explore 5 
   Centauri Psi 	Centauri Genetics Advanced Ecological Engineering 	The Will to Power Secrets of Alpha Centauri Sentient Resonance 	Explore 8 
   Controlled Singularity 	Singularity Mechanics Applied Gravitonics 	String Resonance Transcendent Thought 	Conquer 15 
   Cyberethics 	Planetary Networks Intellectual Integrity 	Superstring Theory Pre-Sentient Algorithms 	Build 4 
   Digital Sentience 	Industrial Nanorobotics Mind/Machine Interface 	Applied Gravitonics Self-Aware Machines Sentient Econometrics 	Discover 10 
   Doctrine: Air Power 	Synthetic Fossil Fuels Doctrine: Flexibility 	Mind/Machine Interface Orbital Spaceflight 	Explore 5 
   Doctrine: Flexibility 	Doctrine: Mobility 	Doctrine: Initiative Doctrine: Air Power Adaptive Doctrine 	Explore 2 
   Doctrine: Initiative 	Doctrine: Flexibility Industrial Automation 	Nanometallurgy Homo Superior 	Explore 4 
   Doctrine: Loyalty 	Doctrine: Mobility Social Psych 	Intellectual Integrity 	Conquer 2 
   Doctrine: Mobility 		Doctrine: Flexibility Doctrine: Loyalty 	Explore 1 
   Ecological Engineering 	Centauri Ecology Gene Splicing 	Centauri Meditation Environmental Economics 	Explore 4 
   Environmental Economics 	Industrial Economics Ecological Engineering 	Advanced Ecological Engineering 	Build 5 
   Ethical Calculus 	Social Psych 	Intellectual Integrity Gene Splicing 	Explore 2 
   Eudaimonia 	Sentient Econometrics The Will to Power 	Temporal Mechanics 	Explore 12 
   Field Modulation (Alien Crossfire only) 	Progenitor Psych Centauri Ecology 	Bioadaptive Resonance 	Conquer 2 
   Frictionless Surfaces 	Unified Field Theory Industrial Nanorobotics 	Quantum Power 	Discover 10 
   Fusion Power 	Pre-Sentient Algorithms Superconductor 	Advanced Ecological Engineering Organic Superlubricant 	Discover 6 
   Gene Splicing 	Biogenetics Ethical Calculus 	Synthetic Fossil Fuels Bio-Engineering Ecological Engineering 	Build 3 
   Graviton Theory 	Quantum Machinery Mind/Machine Interface 	Applied Gravitonics 	Explore 13 
   High Energy Chemistry 	Industrial Base Applied Physics 	Advanced Subatomic Theory Synthetic Fossil Fuels 	Conquer 2 
   Homo Superior 	Biomachinery Doctrine: Initiative 	The Will to Power 	Explore 8 
   Industrial Automation 	Industrial Economics Planetary Networks 	Silksteel Alloys Doctrine: Initiative Neural Grafting Industrial Nanorobotics 	Build 3 
   Industrial Base 		Superconductor High Energy Chemistry Polymorphic Software Industrial Economics 	Build 1 
   Industrial Economics 	Industrial Base 	Industrial Automation Environmental Economics Adaptive Economics 	Build 2 
   Industrial Nanorobotics 	Nanominiaturization Industrial Automation 	Frictionless Surfaces Digital Sentience 	Build 9 
   Information Networks 		Nonlinear Mathematics Polymorphic Software Planetary Networks 	Discover 1 
   Intellectual Integrity 	Ethical Calculus Doctrine: Loyalty 	Cyberethics Planetary Economics 	Explore 3 
   Matter Compression 	Nanometallurgy Nanominiaturization 	Super Tensile Solids 	Conquer 9 
   Matter Editation 	Self-Aware Machines Super Tensile Solids 	Matter Transmission 	Build 12 
   Matter Transmission 	Matter Editation Secrets of Alpha Centauri 	Temporal Mechanics 	Build 13 
   Mind/Machine Interface 	Doctrine: Air Power Neural Grafting 	Graviton Theory Digital Sentience Biomachinery 	Conquer 6 
   Monopole Magnets 	Superstring Theory Silksteel Alloys 	Unified Field Theory Nanominiaturization 	Build 6 
   N-Space Compression (Alien Crossfire only) 	Orbital Spaceflight Biomachinery 	Self-Aware Machines 	Conquer 8 
   Nanometallurgy 	Probability Mechanics Doctrine: Initiative 	Matter Compression Quantum Machinery 	Explore 8 
   Nanominiaturization 	Monopole Magnets Organic Superlubricant 	Matter Compression Industrial Nanorobotics 	Build 8 
   Neural Grafting 	Secrets of the Human Brain Industrial Automation 	Mind/Machine Interface Bio-Engineering 	Conquer 4 
   Nonlinear Mathematics 	Applied Physics Information Networks 	Superstring Theory 	Conquer 2 
   Optical Computers 	Applied Physics Polymorphic Software 	Superconductor Advanced Military Algorithms 	Discover 3 
   Orbital Spaceflight 	Doctrine: Air Power Pre-Sentient Algorithms 	Advanced Spaceflight N-Space Compression 	Discover 6 
   Organic Superlubricant 	Fusion Power Synthetic Fossil Fuels 	Nanominiaturization Advanced Spaceflight 	Conquer 7 
   Photon/Wave Mechanics 	Applied Relativity Silksteel Alloys 	Probability Mechanics 	Conquer 6 
   Planetary Economics 	Adaptive Economics Intellectual Integrity in SMAX, Environmental Economics and Intellectual Integrity in original 	Quantum Power Sentient Econometrics 	Build 6 
   Planetary Networks 	Information Networks 	Industrial Automation Cyberethics 	Discover 2 
   Polymorphic Software 	Industrial Base Information Networks 	Advanced Subatomic Theory Optical Computers Adaptive Doctrine 	Discover 2 
   Pre-Sentient Algorithms 	Advanced Military Algorithms Cyberethics 	Fusion Power Probability Mechanics Orbital Spaceflight 	Discover 5 
   Probability Mechanics 	Photon/Wave Mechanics Pre-Sentient Algorithms 	Nanometallurgy 	Build 7 
   Progenitor Psych (Alien Crossfire only) 		Field Modulation Adaptive Economics 	Explore 1 
   Quantum Machinery 	Quantum Power Nanometallurgy 	Graviton Theory 	Build 12 
   Quantum Power 	Frictionless Surfaces Planetary Economics 	Quantum Machinery 	Discover 11 
   Retroviral Engineering 	Bio-Engineering Advanced Military Algorithms 	Biomachinery Centauri Genetics 	Conquer 6 
   Secrets of Alpha Centauri 	Centauri Psi Sentient Econometrics 	Matter Transmission Secrets of the Manifolds 	Discover 12 
   Secrets of Creation 	Unified Field Theory The Will to Power 	Singularity Mechanics 	Discover 10 
   Secrets of the Human Brain 	Social Psych Biogenetics 	Neural Grafting Centauri Empathy 	Discover 2 
   Secrets of the Manifolds (Alien Crossfire only) 	Sentient Resonance Secrets of Alpha Centauri 	Threshold of Transcendence String Resonance 	Discover 13 
   Self-Aware Machines 	N-Space Compression (Advanced Spaceflight in original), Digital Sentience 	Singularity Mechanics Matter Editation 	Discover 11 
   Sentient Econometrics 	Planetary Economics Digital Sentience 	Eudaimonia Secrets of Alpha Centauri 	Explore 11 
   Sentient Resonance (Alien Crossfire only) 	Bioadaptive Resonance Centauri Psi 	Secrets of the Manifolds 	Conquer 9 
   Silksteel Alloys 	Advanced Subatomic Theory Industrial Automation 	Monopole Magnets Photon/Wave Mechanics 	Build 4 
   Singularity Mechanics 	Secrets of Creation Self-Aware Machines 	Controlled Singularity 	Discover 12 
   Social Psych 		Doctrine: Loyalty Ethical Calculus Secrets of the Human Brain 	Build 1 
   String Resonance (Alien Crossfire only) 	Secrets of the Manifolds Controlled Singularity 		Conquer 16 
   Super Tensile Solids 	Matter Compression Advanced Spaceflight 	Matter Editation 	Build 10 
   Superconductor 	Optical Computers Industrial Base 	Applied Relativity Fusion Power 	Conquer 4 
   Superstring Theory 	Nonlinear Mathematics Cyberethics 	Monopole Magnets 	Conquer 5 
   Synthetic Fossil Fuels 	High Energy Chemistry Gene Splicing 	Doctrine: Air Power Organic Superlubricant 	Explore 4 
   Temporal Mechanics 	Eudaimonia Matter Transmission 	Threshold of Transcendence 	Build 14 
   The Will to Power 	Homo Superior Centauri Psi 	Eudaimonia Secrets of Creation 	Explore 9 
   Threshold of Transcendence 	Secrets of the Manifolds (Secrets of Creation in original), Temporal Mechanics 	Transcendent Thought 	Explore 15 
   Transcendent Thought 	Threshold of Transcendence Controlled Singularity 		Discover 16 
   Unified Field Theory 	Monopole Magnets Applied Relativity 	Frictionless Surfaces Secrets of Creation 	Conquer 7 

""".strip().splitlines()

# Column headers
headers = ["Technology", "Prerequisites", "Leads to", "Track and level"]

# Build AsciiDoc
asciidoc_lines = ['[options="header"]', "|===", "|" + " |".join(headers)]

# Extract headers and initialize grouping dictionary
headers = [h.strip() for h in full_raw_data[0].split("\t")]
tech_by_name = {}

for row in full_raw_data[1:]:
    parts = [p.strip() for p in row.split("\t")]
    if len(parts) != len(headers):
        continue
    row_dict = dict(zip(headers, parts))
    tech_key = row_dict["Track and level"]
    tech_by_name[tech_key] = row_dict

asciidoc_lines.append("|===")

# Save .adoc
asciidoc_output = "\n".join(asciidoc_lines)
output_path = "docs/smac_tech_tree.adoc"
with open(output_path, "w") as f:
    f.write(asciidoc_output)

# Return both outputs
for k, v in tech_by_name.items():
    print(f"{k:>20}: {v}")


# Convert each entry to a Tech object
tech_objects = {}

for tech_id, data in tech_by_name.items():
    leads_to = data["Leads to"].split()  # basic split on space
    tech_objects[tech_id] = Tech(
        name=data["Technology"],
        id=tech_id,
        leads_to=leads_to
    )

for k, v in tech_objects.items():
    print(f"{k:>20}: {v}")
