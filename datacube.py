import itertools as it

import numpy as np

from astropy.io import fits
import astropy.wcs as apywcs
from astropy import units as u


class Datacube(object):

    """
    Base class for spectral line data cubes
    """

    _wcs = None
    _hdu = None

    _dtype = None

    _axis_units = None

    _frequencies = None
    _radio_velocities = None
    _optical_velocities = None

    def __init__(self, path=None, data=None, header=None, **kwargs):

        self._dtype = kwargs.get('dtype', np.float32)

        if path is not None:

            for h in fits.open(path):
                if h.is_image:
                    self._hdu = h
                    break

        elif (data is not None) and (header is not None):

            self._hdu = fits.ImageHDU(data=data, header=header)

        else:
            raise AttributeError(
                "Either path or data and header have to be set.")

        return None

    @property
    def data(self):
        if self._hdu.data.dtype != self._dtype:
            self._hdu.data = self._hdu.data.astype(self._dtype)
        return self._hdu.data

    @property
    def header(self):
        return self._hdu.header

    @property
    def hdu(self):
        return self._hdu

    @property
    def wcs(self):
        if self._wcs is None:
            self._wcs = apywcs.WCS(self.header)
        return self._wcs

    @property
    def spec_wcs(self):
        return self.wcs.sub(['spectral'])

    @property
    def cel_wcs(self):
        return self.wcs.sub(['longitude', 'latitude'])

    @property
    def axis_units(self):
        if self._axis_units is None:
            self._axis_units = [u.Unit(s) for s in self.wcs.wcs.cunit]
        return self._axis_units

    @property
    def radio_velocities(self):
        if self._radio_velocities is None:
            rad_eq = u.doppler_radio(self.wcs.wcs.restfrq * u.Hz)
            self._radio_velocities = self.frequencies.to(u.km / u.s, rad_eq)

        return self._radio_velocities

    @property
    def optical_velocities(self):
        if self._optical_velocities is None:
            opt_eq = u.doppler_optical(self.wcs.wcs.restfrq * u.Hz)
            self._optical_velocities = self.frequencies.to(u.km / u.s, opt_eq)

        return self._optical_velocities

    @property
    def frequencies(self):
        if self._frequencies is None:
            specax = self.wcs.wcs.spec

            channels = np.arange(self.data.shape[::-1][specax])

            specc = self.spec_wcs.wcs_pix2world(channels, 0)[0]
            specc *= self.axis_units[specax]

            # Convert radio or optical velocities to frequencies
            if 'VRAD' in self.wcs.wcs.ctype[specax]:
                eq = u.doppler_radio(self.wcs.wcs.restfrq * u.Hz)
            elif 'VOPT' in self.wcs.wcs.ctype[specax]:
                eq = u.doppler_optical(self.wcs.wcs.restfrq * u.Hz)
            elif 'FREQ' in self.wcs.wcs.ctype[specax]:
                eq = []
            else:
                raise AttributeError(
                    'Unsupported spectral type {:s} in header.'.format(self.wcs.wcs.ctype[specax]))

            self._frequencies = specc.to(u.Hz, eq)

        return self._frequencies


    def radio_velocities_to_channels(self, velocities):
        """
        Return the corresponding channels to the given radio velocities.

        Parameters
        ----------
        velocities : array_like
            Velocities in km/s or as astropy.Quantity to search for

        Returns
        -------
        channels : ndarray
            The channels for the given velocities

        true_velocities : ndarray
            The velocities corresponding to the channels
        """

        # If has unit, convert to radio velocity unit
        # else use dimensionless values
        sv = u.Quantity(velocities)
        if sv.unit is not u.dimensionless_unscaled:
            sv = sv.to(self.radio_velocities.unit).value
        else:
            sv = sv.value

        # If spectral axis is ''reversed'', create sorter array
        if self.radio_velocities[0] > self.radio_velocities[-1]:
            sorter = np.arange(self.radio_velocities.size)[::-1]
        else:
            sorter = None

        channels = np.searchsorted(self.radio_velocities.value, sv, sorter=sorter)

        true_velocities = self.radio_velocities[channels]

        return channels, true_velocities


class DatacubeMoments(object):

    def moment(self, vslice=None, cslice=None, kind=0, mask=None):

        if vslice is not None:
            cslice, _ = self.radio_velocities_to_channels(vslice)
            cslice[-1] += 1

        if cslice is not None:

            cslice = [int(f(c))
                      for f, c in it.izip([np.floor, np.ceil], cslice)]
            data_slice = slice(*cslice)

            if mask is None:
                mask = 1.
            elif mask.shape == self.data.shape[1:]:
                mask = mask[None]
            elif mask.shape == self.data.shape:
                mask = mask[data_slice]

            s_data = self.data[data_slice]

            if kind == 0:
                return np.nansum(s_data * mask, 0)

            if kind == 1:
                s_velocities = self.velocities[data_slice][:, None, None]

                m = np.nansum(s_data * s_velocities * mask, 0)
                m /= np.nansum(s_data * mask, 0)
                return m


class EBHISDatacube(Datacube, DatacubeMoments):

    def __init__(self, *args, **kwargs):

        super(EBHISDatacube, self).__init__(*args, **kwargs)

        self._hdu.header['CUNIT3'] = 'm/s'
        self._hdu.header['CTYPE3'] = 'VRAD'
        self._hdu.header['SPECSYS'] = 'LSRK'
