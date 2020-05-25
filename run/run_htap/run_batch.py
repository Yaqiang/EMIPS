"""
Process emission data by spatial allocation, temporal allocation
and chemical speciation. VOC polluant is not included in this
script.
"""

#Import
import os
import mipylib.numeric as np
from mipylib import dataset
from mipylib import geolib

import emips
from emips.utils import Sector, Units, Weight, Area, Period, \
    emis_util, SectorEnum
from emips.chem_spec import Pollutant, Species, PollutantProfile, \
    SpeciesProfile, PollutantEnum, SpeciesEnum
from emips.spatial_alloc import GridDesc, transform
from emips import ge_data_dir

def run(year, month, dir_inter, emission, model_grid):
    """
    Process emission data by spatial allocation, temporal allocation
    and chemical speciation except VOC pollution.

    :param year: (*int*) Year.
    :param month: (*int*) Month.
    :param dir_inter: (*string*) Data output path.
    :param emission: (*module*) Emission module.
    :param model_grid: (*GridDesc*) Model data grid describe.
    """
    #Set profile files
    temp_profile_fn = os.path.join(ge_data_dir, 'amptpro.m3.default.us+can.txt')
    temp_ref_fn = os.path.join(ge_data_dir, 'amptref.m3.us+can.cair.txt')
    spec_profile_fn = os.path.join(ge_data_dir, 'gspro.cmaq.radm2p25_rev.txt')
    spec_ref_fn = os.path.join(ge_data_dir, 'gsref.cmaq.radm2p25.txt')
    
    #Set data dimensions
    tdim = dataset.dimension(np.arange(24), 'hour')
    ydim = dataset.dimension(model_grid.y_coord, 'lat', 'Y')
    xdim = dataset.dimension(model_grid.x_coord, 'lon', 'X')
    dims = [tdim, ydim, xdim]
    
    #Set sectors and pollutants
    sectors = [SectorEnum.INDUSTRY, SectorEnum.AGRICULTURE, SectorEnum.ENERGY, \
        SectorEnum.RESIDENTIAL, SectorEnum.TRANSPORT, SectorEnum.SHIPS, \
        SectorEnum.AIR]
    
    pollutants = [PollutantEnum.BC, PollutantEnum.CH4, PollutantEnum.CO, \
        PollutantEnum.NH3, PollutantEnum.NOx, PollutantEnum.OC, PollutantEnum.PM2_5, \
        PollutantEnum.SO2, PollutantEnum.PM10]
    out_species = [SpeciesEnum.PEC, SpeciesEnum.CH4, SpeciesEnum.CO, SpeciesEnum.NH3, \
        None, SpeciesEnum.POA, None, SpeciesEnum.SO2, SpeciesEnum.PMC]
    
    #Loop
    for sector in sectors:
        print('####################################')
        print(sector)
        print('####################################')
        
        #Get SCC
        scc = emis_util.get_scc(sector)
        
        #Get pollutant profiles
        pollutant_profiles = emips.chem_spec.read_file(spec_ref_fn, spec_profile_fn, scc)
        for pollutant, out_spec in zip(pollutants, out_species):
            print(pollutant)
    
            print('Read emission data (kg/m2/s)...')
            emis_data = emission.read_emis(sector, pollutant, year, month)
            if emis_data is None:    #No emission of a pollutant for some sectors
                continue
            
            #### Spatial allocation        
            print('Spatial allocation of emission grid to model grid...')
            emis_data = transform(emis_data, emission.emis_grid, model_grid)        
            
            #### Temporal allocation
            print('Temporal allocation...')
            month_profile, week_profile, diurnal_profile, diurnal_profile_we = \
                emips.temp_alloc.read_file(temp_ref_fn, temp_profile_fn, scc)
            if pollutant == PollutantEnum.CH4 or sector == SectorEnum.AIR or \
                sector == SectorEnum.SHIPS:
                print('To (kg/m2/year)')
                emis_data = emis_data * 3600 * 24 * emis_util.get_year_days(year)
                print('To monthly emission (kg/m2/month)...')
                emis_data = emips.temp_alloc.month_allocation(emis_data, month_profile)
                emis_data = emis_data[month - 1] 
            else:
                print('To (kg/m2/month)')
                emis_data = emis_data * 3600 * 24 * emis_util.get_month_days(year, month)
                      
            print('To daily emission (kg/m2/day)...')
            weekday_data, weekend_data = emips.temp_alloc.week_allocation(emis_data, week_profile, year, month)
            print('To hourly emission (g/m2/s)...')
            hour_data = emips.temp_alloc.diurnal_allocation(weekday_data, diurnal_profile) / 3.6
    
            #### Chemical speciation
            poll_prof = emips.chem_spec.get_pollutant_profile(pollutant_profiles, pollutant)
            if (pollutant == PollutantEnum.NOx) and (poll_prof is None):
                poll_prof = PollutantProfile(pollutant)
                poll_prof.append(SpeciesProfile(pollutant, SpeciesEnum.NO, 0.9, 1.0, 0.9))
                poll_prof.append(SpeciesProfile(pollutant, SpeciesEnum.NO2, 0.1, 1.0, 0.1))
    
            #### Set output netcdf file path    
            outfn = os.path.join(dir_inter, \
                '{}_emis_{}_{}_{}_hour.nc'.format(pollutant.name, sector.name, year, month))
            print outfn
            if poll_prof is None:
                #### Save hourly emission data
                print('Save hourly emission data...')        
                if out_spec.molar_mass is None:           
                    attrs = dict(units='g/m2/s')
                else:
                    attrs = dict(units='mole/m2/s')
                    hour_data = hour_data / out_spec.molar_mass
                dataset.ncwrite(outfn, hour_data, out_spec.name, dims, attrs)
            else:
                print('Chemical speciation...')
                specs = poll_prof.get_species()
                gattrs = dict(Conventions='CF-1.6', Tools='Created using MeteoInfo')
                dimvars = []
                for spec in specs:
                    dimvar = dataset.DimVariable()
                    dimvar.name = spec.name
                    dimvar.dtype = np.dtype.float
                    dimvar.dims = dims
                    if spec.molar_mass is None:
                        dimvar.addattr('units', 'g/m2/s')
                    else:
                        dimvar.addattr('units', 'mole/m2/s')
                    dimvars.append(dimvar)
                ncfile = dataset.addfile(outfn, 'c')
                ncfile.nc_define(dims, gattrs, dimvars)
                for spec_prof,dimvar,spec in zip(poll_prof.species_profiles, dimvars, specs):
                    print(dimvar.name)
                    if spec.molar_mass is None:
                        spec_data = hour_data * spec_prof.mass_fraction
                    else:
                        spec_data = hour_data * spec_prof.mass_fraction / spec.molar_mass
                    ncfile.write(dimvar.name, spec_data)
                ncfile.close()

if __name__ == '__main__':
    #Set current working directory
    from inspect import getsourcefile
    dir_run = os.path.dirname(os.path.abspath(getsourcefile(lambda:0)))
    if not dir_run in sys.path:
        sys.path.append(dir_run)  
    import emission_htap_2010 as emission

    #Set year, month and output data path
    year = 2010
    month = 1
    dir_inter = r'D:\run_data\emips\run_htap\inter_data\{}{:>02d}'.format(year, month)
    if not os.path.exists(dir_inter):
        os.mkdir(dir_inter)

    #Set model grids
    proj = geolib.projinfo()
    model_grid = GridDesc(proj, x_orig=70., x_cell=0.15, x_num=502,
        y_orig=15., y_cell=0.15, y_num=330)

    #Run
    run(year, month, dir_inter, emission, model_grid)