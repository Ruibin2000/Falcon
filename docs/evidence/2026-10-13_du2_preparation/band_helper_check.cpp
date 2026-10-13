#include "ocudu/ran/band_helper.h"
#include <iostream>
using namespace ocudu;
int main() {
  for (unsigned arfcn : {644000U, 640000U}) {
    auto loc = band_helper::get_ssb_coreset0_freq_location(arfcn, nr_band::n78, 51,
      subcarrier_spacing::kHz30, subcarrier_spacing::kHz30, search_space0_index{0}, 2);
    if (!loc) return 1;
    std::cout << "carrier=" << arfcn << " ssb=" << loc->ssb_arfcn.value()
      << " offsetToPointA=" << loc->offset_to_point_A.value()
      << " kSSB=" << unsigned(loc->k_ssb.value())
      << " CORESET0=" << unsigned(loc->coreset0_idx.value())
      << " SS0=" << unsigned(loc->searchspace0_idx.value()) << "\n";
  }
}
