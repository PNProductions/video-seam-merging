# coding=UTF-8
from numpy import max, concatenate, size, ones, r_, zeros, inf, amax, where, shape, copy, append, empty
import numpy as np
from random import random
import numexpr as ne
from seammerging.native import improved_sum_shifted
from seammerging.utils import cli_progress_bar, cli_progress_bar_end


class SeamMergingWithDecomposition(object):
  #
  # X: input image
  # S: skeletal(cartoon) image of the input image
  # T: importance map
  # deleteNumberW  : Number of columns to be deleted
  # deleteNumberH  : Number of rows to be deleted
  #
  def __init__(self, X, S, T, deleteNumberW, deleteNumberH, alpha, beta):
    self.X = X
    self.S = S
    self.T = T / max(max(T))
    self.deleteNumberW = deleteNumberW
    self.deleteNumberH = deleteNumberH
    self.alpha = alpha
    self.beta = beta
    self.gamma = 1 - alpha

  def initD(self, Simg):
    return zeros((size(Simg, 0), size(Simg, 1) - 1))

  ## Initialization method to normalize weights of the algorithm, calculating the max energy dynamic programming should reach.
  # @imp Importance map, generated by the image
  # @CU 
  # @CW
  # @CE
  # @CL
  # @CR
  # 
  # Returns:
  # @alpha Normalized alpha
  # @gamma Normalized gamma
  # @beta Normalized beta
  def initializeParameters(self, imp, CU, CW, CE, CL, CR):
    # Maximum path of importance
    Pot = copy(imp)
    for ii in xrange(1, size(Pot, 0)):
      pp = Pot[ii - 1, :]
      energy3 = zeros((size(Pot, 1), 3))
      # Energy in the case of a seam that binds to L
      energy3[:, 0] = concatenate(([0], pp[0:-1]))  # The left side of the screen is not calculated
      # Energy in the case of a seam that binds to U
      energy3[:, 1] = pp
      # Energy in the case of a seam that binds to the R
      energy3[:, 2] = append(pp[1:], 0)  # The right edge of the screen is not calculated
      Pot[ii, :] = Pot[ii, :] + energy3.max(axis=1)

    impMax = Pot[-1, :].max()

    Pot = self.dynamic_programming(CW + CE, CU, CL, CR)

    strMax = Pot[-1, :].max()
    iteMax = size(imp, 0)

    return self.alpha / strMax, self.gamma / impMax, self.beta / iteMax

  ## Dynamic programming algorithm to generate iteratively the actual energy map M(r).
  # @Pot The initial energy map, already initialized with the energy values E(r) for each pixels r
  # @CU Energy of choosing the upper direction
  # @CL Energy of choosing the upper-left direction
  # @CR Energy of choosing the upper-right direction
  #
  # Returns:
  # @Pot M(r).
  # @pathMap A matrix that says, for each position, which is the best direction to take in order to minimize energy.
  #          It contains 0 = left, 1 = up, 2 = right
  def dynamic_programming(self, Pot, CU, CL, CR, pathMap=None):
    r = np.arange(Pot.shape[1])
    # Each row i of Pot depends on the previous one i - 1
    for ii in xrange(1, size(Pot, 0)):
      # Previous row
      pp = Pot[ii - 1, :]
      # We use a support matrix energy3, with 3 components.
      # The first one depends on CL, the second on CU, the third on CR
      energy3 = empty((size(Pot, 1), 3))
      # In the first component, the first element is infinite because it can't be chosen (there isn't a left pixel of the left-most pixel)
      energy3[0, 0] = inf
      # e[i] = pp[i-1, j-1] + CL[i, j]
      energy3[1:, 0] = pp[0:-1] + CL[ii, 1:]

      energy3[:, 1] = pp + CU[ii, :]

      # In the last component, as last element we set infinite for the same reason
      # e[i] = pp[i-1, j+1] + CR[i, j]
      #energy3[:, 2] = append(pp[1:] + CR[ii, 0:-1], inf)
      energy3[0:-1, 2] = pp[1:] + CR[ii, 0:-1]
      energy3[-1, 2] = inf

      if pathMap is None:
        # From the paper: M(r) = E(r) + min {  }
        Pot[ii, :] = Pot[ii, :] + energy3.min(axis=1)
      else:
        args = energy3.argmin(axis=1)
        pathMap[ii, :] = args
        Pot[ii, :] = Pot[ii, :] + energy3[r, args]

    return Pot

  ## Given the actual state matrixes of the algorithm, it applies the seam merging to each of them.
  # @I A vector that maps a certain row with a certain column, and represents which pixel of each row should be merged with the right neighbour
  # @q11 A matrix for mean pixel value calculation
  # @upQ11 Look-forward version of q11 (representing the value of every pixel merged with its right neighbour)
  # @q12 The actual inverse value of the skeletal image, without applying the mean value
  # @upQ12 Look-forward version of q12
  # @p12 A 4-components (that represents the four directions) structure of the image. See initialization for more details.
  # @upP12 Look-forward version of p12
  # @p22 The square value of p12 (p12**2), precomputed.
  # @upP22 Look-forward version of p22
  # @Simg The actual skeletal image value (with the mean applied). It's equivalent to -q12/q11
  # @v The look-forward version of Simg
  # @Z A matrix that contains the original image, the structure image and a matrix of ones.
  #
  # Returns:
  # All the updated matrixes ready for the next iteration
  #
  # This method applies the merge in two steps:
  # * Deletion: For each row, deletes a value according to I.
  # * Merge/substitution: For each row, it replaces the actual value of the seam with it's look-forwarded version, according to I
  # The only exception is Z, that is not precomputed and should be calculated in real time.
  def apply_seam_merging(self, I, q11, upQ11, q12, upQ12, p12, upP12, p22, upP22, Simg, v, Z):
    reduced_size_1, reduced_size_2 = size(Simg, 0), size(Simg, 1) - 1

    ## Deletion:
    # Generating a deletion mask n x m. It's a binary matrix that contains True if the pixel should be keeped, False if they should be deleted.
    # The total number of Falses and Trues at each like should be the same.
    # Applying that matrix to a standard numpy array, it efficiently generates a clone matrix with the deleted values
    mask = np.arange(size(Z, 1)) != np.vstack(I)
    # After applying the mask, the new vector generated is flattened, so you should reshape it.
    q11Copy = q11[mask].reshape(reduced_size_1, reduced_size_2)
    q12Copy = q12[mask].reshape(reduced_size_1, reduced_size_2)

    SimgCopy = Simg[mask].reshape(reduced_size_1, reduced_size_2)

    p12Copy = p12[mask].reshape(reduced_size_1, reduced_size_2, p12.shape[2])
    p22Copy = p22[mask].reshape(reduced_size_1, reduced_size_2, p22.shape[2])
    ZCopy = Z[mask].reshape(reduced_size_1, reduced_size_2, Z.shape[2])

    ## Merge:
    # I is converted to an integer matrix, in order to be used as an index map.
    # This can achieve a non-aligned multirow substitution very efficiently
    # Every indexed value of the seam is replaced with it's look-forward version.
    I = I.astype(np.uint32)
    r = r_[0:size(I)]
    q11Copy[r, I] = upQ11[r, I]
    q12Copy[r, I] = upQ12[r, I]

    p12Copy[r, I, :] = upP12[r, I]
    p22Copy[r, I, :] = upP22[r, I]

    SimgCopy[r, I] = v[r, I]
    # Z lookforward version is not precomputed, so you have to do it in real time
    ZCopy[r, I, :] = Z[r, I, :] + Z[r, I + 1, :]

    return q11Copy, q12Copy, p12Copy, p22Copy, SimgCopy, ZCopy

  ## Starting from the energy map and the path map, it generates vector pix, a vector that maps, for each row, the column of the seam to be merged.
  # @Pot The energy map. The position of minimum value of the last row of Pot represents the starting pixel of the seam (with a bottom-up strategy)
  # @pathMap A matrix that maps, for each position, the best direction to be taken to find the lower energy seam.
  #
  # Returns:
  # @pix the seam coordinates map.
  #
  # Example:
  # pix = [3, 4, 5, 5, 4, 5]
  # That maps this list of coordinates:
  # (0, 3), (1, 4), (2, 5), (3, 5), (4, 5), (5, 5)
  def generateSeamPath(self, Pot, pathMap):
    s_Pot_1 = Pot.shape[0]

    pix = empty((s_Pot_1, 1))
    Pot_last_line = Pot[-1, :]

    # mn, pix[-1] = Pot_last_line.min(axis=0), Pot_last_line.argmin(axis=0)
    # Finding the minimum value from Pot's last line's values.
    mn = Pot_last_line.min(axis=0)

    # Searching the list of indexes that have the minimum energy
    pp = where(Pot_last_line == mn)[0]

    # If there's more than one, it's random choosen
    pix[-1] = pp[int(random() * amax(pp.shape))]
    # Starting from the bottom
    for ii in reversed(xrange(0, s_Pot_1 - 1)):  # xrange(s_Pot_1 - 2, -1, -1):
      # Directions expressed in pathMap uses this rule: 0 => upper-left, 1 => upper, 2 => upper-right
      # They are remapped to be like that: -1 => upper-left, 0 => upper, 1 => upper-right
      # To calculate the coordinate at step ii, you should map with: coordinate(ii + 1) + remapped direction
      pix[ii] = pix[ii + 1] + pathMap[ii + 1, int(pix[ii + 1])] - 1
    return pix

  def generateNorthEnergy(self, Simg, v, northA, northB, northC):
    square = self.square
    DD = self.initD(Simg)
    DD[1:, :] = v[1:, :] - v[0:-1, :]  # Dovrebbe essere c_0(q, n)
    CNcc = square(DD, northA, northB, northC)  # Dovrebbe essere ||c_k(q, n) - c_0(q, n)||^2

    # Upper-left connection
    DD = np.zeros_like(DD)
    DD[1:, 1:] = v[1:, 1:] - Simg[0:-1, 2:]
    CNcnCL = square(DD, northA, northB, northC)

    # Upper-right connection
    DD = np.zeros_like(DD)
    DD[1:, 0:-1] = v[1:, 0:-1] - Simg[0:-1, 0:-2]
    CNcnCR = square(DD, northA, northB, northC)
    return CNcc, CNcnCL, CNcnCR

  def generateSouthEnergy(self, Simg, v, southA, southB, southC):
    square = self.square
    # Lower connection
    # CScc = || Structure_k+1 - Structure_k ||_2 in south direction
    # Structure_k+1 = Skel(r) - Skel(r-1) # (r = pixel)

    DD = self.initD(Simg)
    DD[0:-1, :] = v[0:-1, :] - v[1:, :]
    CScc = square(DD, southA, southB, southC)

    # Lower-left connection
    DD = np.zeros_like(DD)
    DD[0:-1, 0:-1] = v[0:-1, 0:-1] - Simg[1:, 0:-2]
    CScnCL = square(DD, southA, southB, southC)

    # Lower-right connection
    DD = np.zeros_like(DD)
    DD[0:-1, 1:] = v[0:-1, 1:] - Simg[1:, 2:]
    CScnCR = square(DD, southA, southB, southC)

    return CScc, CScnCL, CScnCR

  def generateEastEnergy(self, Simg, v, eastA, eastB, eastC):
    DD = self.initD(Simg)
    DD[:, 0:-1] = v[:, 0:-1] - Simg[:, 2:]
    return self.square(DD, eastA, eastB, eastC)

  def generateWestEnergy(self, Simg, v, westA, westB, westC):
    DD = self.initD(Simg)
    DD[:, 1:] = v[:, 1:] - Simg[:, 0:-2]
    return self.square(DD, westA, westB, westC)

  def generateEnergyUpLeftRight(self, CScc, CNcc, CScnCL, CNcnCL, CScnCR, CNcnCR):
    CU = zeros(CScc.shape)
    # Qui non è niente di che: CS e CN sono disallineate, perché sono una rispetto al nord e una rispetto al sud
    # e devo riallinearle per poterle sommare correttamente.
    CU[1:, :] = CScc[0:-1, :] + CNcc[1:, :]

    CL = zeros(CScc.shape)
    CL[1:, 1:] = CScnCL[0:-1, 0:-1] + CNcnCL[1:, 1:]

    CR = zeros(CScc.shape)
    CR[1:, 0:-1] = CScnCR[0:-1, 1:] + CNcnCR[1:, 0:-1]
    return CU, CL, CR

  def divide(self, a, b):
    return ne.evaluate('- a / b')

  def square(self, DD, a, b, c):
    return ne.evaluate('a * (DD ** 2) + 2 * b * DD + c')

  def calculatePot(self, CW, CE, alphaN, imp, gammaN, ite, betaN):
    return ne.evaluate('(CW + CE) * alphaN + imp * gammaN + betaN * ite')

  def sumShifted(self, a):
    return a[:, 0:-1] + a[:, 1:]

  def generate(self):
    sumShifted = self.sumShifted
    X, S, T = self.X, self.S, self.T

    # Precomputed sizes
    s_X_1, s_X_2, s_X_3 = size(X, 0), size(X, 1), size(X, 2)
    s_T_1, s_T_2, s_T_3 = size(T, 0), size(T, 1), 1# size(T, 2) TO BE FIXED!!!
    s_S_1, s_S_2 = size(S, 0), size(S, 1)

    # Z is a matrix that contains both the image S, the matrix T (Importance Map),
    # and a matrix of ones. Each component looks like: [X_0, X_1, X_2, T_0, 1]
    Z = concatenate((X, T.reshape(s_T_1, s_T_2, s_T_3), ones((s_X_1, s_X_2, 1))), axis=2)
    s_Z_1, s_Z_2, s_Z_3 = size(Z, 0), size(Z, 1), size(Z, 2)


    # A fast way to index all components of Z that contains the components of X
    ZIindex = r_[0:s_X_3]
    # A fast way to index all components of Z that contains the components of T
    ZTindex = s_X_3 + r_[0:s_T_3]
    # A fast way to index all components of Z that contains the ones
    ZUindex = s_Z_3 - 1
    # Both T and ones indexes together
    ZTUindex = append(ZTindex, ZUindex)

    # q11 is a matrix of ones. It's used as to calculate the correct mean value of
    # pixel values of the merged image. Ad each position contains a value so that
    # p12 / that_value = mean value of the image in that position.
    q11 = ones(shape(S), order='C')
    # Precomputed value of -S (skeleton image). It's updated every frame and
    # represents the actual value of the skeleton seam-merged skeleton image
    q12 = np.ascontiguousarray(-S)

    # list of indexes for easy access to p12 matrix's components
    up, down, right, left = 0, 1, 2, 3

    # p12 is a matrix with four components, one for each direction. It represents
    # the structure value of each pixel of the image as a difference between
    # the gamma value of that pixel and it's neighbour.
    # On the paper it's called c(r)
    p12 = zeros((s_S_1, s_S_2, 4))
    # Upper connection
    # C(r, 0)
    # p12[:, :, up] = concatenate((zeros((1, s_S_2)), S[1:, :] - S[0:-1, :]))  # [[zeros(1, size(S, 2))], [S[1:, :] - S[-2, :]]]
    p12[1:, :, up] = S[1:, :] - S[0:-1, :]  # [[zeros(1, size(S, 2))], [S[1:, :] - S[-2, :]]]
    # Lower connection
    # C(r, 1)
    # p12[:, :, down] = concatenate((S[0:-1, :] - S[1:, :], zeros((1, s_S_2))))  # [[S[-2, :] - S[1:, :]], [zeros(1, size(S, 2))]]
    p12[0:-1, :, down] = S[0:-1, :] - S[1:, :]  # [[S[-2, :] - S[1:, :]], [zeros(1, size(S, 2))]]
    # Right connection
    # C(r, 2)
    # p12[:, :, right] = concatenate((S[:, 0:-1] - S[:, 1:], zeros((s_S_1, 1))), axis=1)
    p12[:, 0:-1, right] = S[:, 0:-1] - S[:, 1:]
    # Left connection
    # C(r, 3)
    # p12[:, :, left] = concatenate((zeros((s_S_1, 1)), S[:, 1:] - S[:, 0:-1]), axis=1)
    p12[:, 1:, left] = S[:, 1:] - S[:, 0:-1]

    # Precomputing inverse value for mean-square calculation
    p12 = -p12
    # Precomputing square value of p12 for mean-square calculation
    p22 = p12 ** 2

    # Cloning S [To be fixed]
    Simg = S

    alphaN, gammaN, betaN = 0, 0, 0

    # upQ11, upQ12, upP12, upP22 = None, None, None, None

    # For each seam I want to merge
    num_seams = self.deleteNumberW + self.deleteNumberH
    for i in xrange(0, num_seams):
      cli_progress_bar(i, num_seams)

      # Improved sum shifted = summing each column of the pixel with the
      # one in the right. It's the look-forward value for each matrix.
      # matrix
      upQ11, upQ12, upP12, upP22 = improved_sum_shifted(q11, q12, p12, p22)

      # v is the mean look-forward value of S, for each pixel
      v = self.divide(upQ12, upQ11)

      # Upper connection
      # Temporary matrixes that represents differences between a pixel
      # and its northen neighbour.
      CNcc, CNcnCL, CNcnCR = self.generateNorthEnergy(Simg, v, upQ11, upP12[:, :, up], upP22[:, :, up])

      # Lower connection
      # The same with the southern neighbour.
      CScc, CScnCL, CScnCR = self.generateSouthEnergy(Simg, v, upQ11, upP12[:, :, down], upP22[:, :, down])

      # Right connection
      CE = self.generateEastEnergy(Simg, v, upQ11, upP12[:, :, right], upP22[:, :, right])

      # Left connection
      CW = self.generateWestEnergy(Simg, v, upQ11, upP12[:, :, left], upP22[:, :, left])

      # Error when binding a row on was just above
      CU, CL, CR = self.generateEnergyUpLeftRight(CScc, CNcc, CScnCL, CNcnCL, CScnCR, CNcnCR)

      # Calculating future-value for both importance map and ones, that is the sum
      # of a pixel with its right-most neighbour.
      Z_T = Z[:, :, ZTUindex]
      temp = sumShifted(Z_T)
      imp = temp[:, :, 0]
      # imp = self.sumShifted(Z[:, :, ZTindex], Z[:, :, ZTindex])

      ite = temp[:, :, 1]
      # ite = self.sumShifted(Z[:, :, ZUindex], Z[:, :, ZUindex])  # Z[:, 0:-1, ZUindex] + Z[:, 1:, ZUindex]
      # This step is quite useless if importance map and ones map is a single component matrix
      if size(ZTUindex) > 2:
        imp = imp.sum(axis=2)
        ite = ite.sum(axis=2)

      # Calculating the maximum possible value for alpha, beta, gamma, dividing their
      # values by the maximum value that can be obtained by dynamic programming results.
      if i == 0:
        alphaN, gammaN, betaN = self.initializeParameters(imp, CU, CW, CE, CL, CR)

      # Calcolo i valori iniziali di E(r).
      # Pot is initialized with E values for each pixel
      # Pot is M in the paper, and it's defined as:
      # Pot(i+1) = E(i) + min { ???? }
      Pot = self.calculatePot(CW, CE, alphaN, imp, gammaN, ite, betaN)

      # Weighing CU CR and CL with input weight.
      CU, CR, CL = ne.evaluate('CU * alphaN'), ne.evaluate('CR * alphaN'), ne.evaluate('CL * alphaN')

      # pathmap is a matrix that, for each position, specifies the best direction
      # to be taken to minimize the cost.
      pathMap = zeros(Pot.shape)
      Pot = self.dynamic_programming(Pot, CU, CL, CR, pathMap)

      pix = self.generateSeamPath(Pot, pathMap)

      q11, q12, p12, p22, Simg, Z = self.apply_seam_merging(pix.transpose()[0], q11, upQ11, q12, upQ12, p12, upP12, p22, upP22, Simg, v, Z)

    cli_progress_bar_end()
    img = Z[:, :, ZIindex]
    img = img / Z[:, :, [ZUindex, ZUindex, ZUindex]]  # ???
    return img
