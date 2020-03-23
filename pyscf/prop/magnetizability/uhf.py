#!/usr/bin/env python
# Copyright 2014-2019 The PySCF Developers. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Author: Qiming Sun <osirpt.sun@gmail.com>
#

'''
Non-relativistic magnetizability tensor for UHF
(In testing)

Refs:
[1] R. Cammi, J. Chem. Phys., 109, 3185 (1998)
[2] Todd A. Keith, Chem. Phys., 213, 123 (1996)
'''


import time
import numpy
from pyscf import lib
from pyscf.lib import logger
from pyscf.scf import jk
from pyscf.prop.nmr import uhf as uhf_nmr
from pyscf.prop.magnetizability import rhf as rhf_mag


def dia(magobj, gauge_orig=None):
    mol = magobj.mol
    mf = magobj._scf
    mo_energy = mf.mo_energy
    mo_coeff = mf.mo_coeff
    mo_occ = mf.mo_occ
    orboa = mo_coeff[0][:,mo_occ[0] > 0]
    orbob = mo_coeff[1][:,mo_occ[1] > 0]
    dm0a = numpy.dot(orboa, orboa.T)
    dm0b = numpy.dot(orbob, orbob.T)
    dm0 = dm0a + dm0b
    dme0a = numpy.dot(orboa * mo_energy[0][mo_occ[0] > 0], orboa.T)
    dme0b = numpy.dot(orbob * mo_energy[1][mo_occ[1] > 0], orbob.T)
    dme0 = dme0a + dme0b

    e2 = rhf_mag._get_dia_1e(magobj, gauge_orig, dm0, dme0).ravel()

    if gauge_orig is None:
        vs = jk.get_jk(mol, [dm0, dm0a, dm0a, dm0b, dm0b],
                       ['ijkl,ji->s2kl',
                        'ijkl,jk->s1il', 'ijkl,li->s1kj',
                        'ijkl,jk->s1il', 'ijkl,li->s1kj'],
                       'int2e_gg1', 's4', 9, hermi=1)
        e2 += numpy.einsum('xpq,qp->x', vs[0], dm0)
        e2 -= numpy.einsum('xpq,qp->x', vs[1], dm0a) * .5
        e2 -= numpy.einsum('xpq,qp->x', vs[2], dm0a) * .5
        e2 -= numpy.einsum('xpq,qp->x', vs[3], dm0b) * .5
        e2 -= numpy.einsum('xpq,qp->x', vs[4], dm0b) * .5

        vk = jk.get_jk(mol, [dm0a, dm0b], ['ijkl,jk->s1il', 'ijkl,jk->s1il'],
                       'int2e_g1g2', 'aa4', 9, hermi=0)
        e2 -= numpy.einsum('xpq,qp->x', vk[0], dm0a)
        e2 -= numpy.einsum('xpq,qp->x', vk[1], dm0b)

    return -e2.reshape(3, 3)


# Note mo10 is the imaginary part of MO^1
def para(magobj, gauge_orig=None, h1=None, s1=None, with_cphf=None):
    '''Paramagnetic susceptibility tensor

    Kwargs:
        h1: A list of arrays. Shapes are [(3,nmo_a,nocc_a), (3,nmo_b,nocc_b)]
            First order Fock matrices in MO basis.
        s1: A list of arrays. Shapes are [(3,nmo_a,nocc_a), (3,nmo_b,nocc_b)]
            First order overlap matrices in MO basis.
        with_cphf : boolean or  function(dm_mo) => v1_mo
            If a boolean value is given, the value determines whether CPHF
            equation will be solved or not. The induced potential will be
            generated by the function gen_vind.
            If a function is given, CPHF equation will be solved, and the
            given function is used to compute induced potential
    '''
    log = logger.Logger(magobj.stdout, magobj.verbose)
    cput1 = (time.clock(), time.time())

    mol = magobj.mol
    mf = magobj._scf
    mo_energy = mf.mo_energy
    mo_coeff = mf.mo_coeff
    mo_occ = mf.mo_occ
    orboa = mo_coeff[0][:,mo_occ[0] > 0]
    orbob = mo_coeff[1][:,mo_occ[1] > 0]

    if h1 is None:
        # Imaginary part of F10
        dm0 = (numpy.dot(orboa, orboa.T), numpy.dot(orbob, orbob.T))
        h1 = magobj.get_fock(dm0, gauge_orig)
        h1 = (lib.einsum('xpq,pi,qj->xij', h1[0], mo_coeff[0].conj(), orboa),
              lib.einsum('xpq,pi,qj->xij', h1[1], mo_coeff[1].conj(), orbob))
        cput1 = log.timer('first order Fock matrix', *cput1)
    if s1 is None:
        # Imaginary part of S10
        s1 = magobj.get_ovlp(mol, gauge_orig)
        s1 = (lib.einsum('xpq,pi,qj->xij', s1, mo_coeff[0].conj(), orboa),
              lib.einsum('xpq,pi,qj->xij', s1, mo_coeff[1].conj(), orbob))

    with_cphf = magobj.cphf
    mo1, mo_e1 = uhf_nmr.solve_mo1(magobj, mo_energy, mo_coeff, mo_occ,
                                   h1, s1, with_cphf)
    cput1 = logger.timer(magobj, 'solving mo1 eqn', *cput1)

    occidxa = mo_occ[0] > 0
    occidxb = mo_occ[1] > 0
    mag_para = numpy.einsum('yji,xji->xy', mo1[0], h1[0])
    mag_para+= numpy.einsum('yji,xji->xy', mo1[1], h1[1])
    mag_para-= numpy.einsum('yji,xji,i->xy', mo1[0], s1[0], mo_energy[0][occidxa])
    mag_para-= numpy.einsum('yji,xji,i->xy', mo1[1], s1[1], mo_energy[1][occidxb])
    # + c.c.
    mag_para = mag_para + mag_para.conj()

    mag_para-= numpy.einsum('xij,yij->xy', s1[0][:,occidxa], mo_e1[0])
    mag_para-= numpy.einsum('xij,yij->xy', s1[1][:,occidxb], mo_e1[1])
    return -mag_para


class Magnetizability(rhf_mag.Magnetizability):
    dia = dia
    para = para
    get_fock = uhf_nmr.get_fock


if __name__ == '__main__':
    from pyscf import gto
    from pyscf import scf
    mol = gto.Mole()
    mol.verbose = 7
    mol.output = '/dev/null'
    mol.atom = '''h  ,  0.   0.   0.
                  F  ,  0.   0.   .917'''
    mol.basis = '631g'
    mol.build()

    mf = scf.UHF(mol).run()
    mag = Magnetizability(mf)
    mag.cphf = True
    m = mag.kernel()
    print(lib.finger(m) - -0.43596639996758657)

    mag.gauge_orig = (0,0,1)
    m = mag.kernel()
    print(lib.finger(m) - -0.76996086788058238)

    mag.gauge_orig = (0,0,1)
    mag.cphf = False
    m = mag.kernel()
    print(lib.finger(m) - -0.7973915717274408)


    mol = gto.M(atom='''O      0.   0.       0.
                        H      0.  -0.757    0.587
                        H      0.   0.757    0.587''',
                basis='ccpvdz', spin=2)
    mf = scf.UHF(mol).run()
    mag = Magnetizability(mf)
    mag.cphf = True
    m = mag.kernel()
    print(lib.finger(m) - -4.6700053640388353)
